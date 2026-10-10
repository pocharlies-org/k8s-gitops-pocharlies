/**
 * WhatsApp statuses ("Estados") and channel posts (fase 3 follow-up, the
 * store / read / publish half of the NAS fork's "novedades", adapted to prod).
 *
 * Where things live (measured on prod, 01-10):
 *  - a status is a message of `status@broadcast`: it already lands in
 *    `messages` (conversation `status@broadcast` of the account) with its media
 *    in `attachments`, like any message, and that does not change here.
 *    whatsapp_statuses (mcp-server migration 019) is the index on top: one
 *    row per status with its author, posted_at and expires_at (+24 h), so
 *    "recent statuses" and "statuses of one contact" read an index instead of
 *    `messages`. Content, type, media and revokes are JOINed from `messages`;
 *  - a channel (newsletter) post is a message of `<id>@newsletter`: it lands
 *    in `messages` too, one conversation per channel. Listing posts is a query
 *    over `messages` (no copy, no table of its own).
 *
 * Rules (same as message-stars-pins.ts):
 *  - ids use the SAME namespacing as `messages` (accountKey);
 *  - the table is created by the migration, never here. While it is missing
 *    every call fails soft: 42P01 is logged once, writes answer false and the
 *    status list answers empty with persisted: false. Re-probed every few
 *    minutes, so no restart is needed once the migration lands;
 *  - publishing a status is behind WA_STATUS_PUBLISH_ENABLED (default off,
 *    set in no overlay) on top of the send gate, with confirm: true and an
 *    explicit list of recipients: a status goes to every listed contact.
 *
 * The caller (BaileysClient) only calls in here when `ingest` is on: the
 * per-sub pairing pool never touches these tables.
 */
import { jidNormalizedUser } from '@whiskeysockets/baileys';
import { accountKey, connectorAccount, getPool, stripAccountKey } from './db-writer';
import { MessageMutationError, whatsappAccountId } from './message-mutations';
import { externalIdCandidates } from './chat-state';

const UNDEFINED_TABLE = '42P01';
const MISSING_TABLE_RECHECK_MS = 5 * 60 * 1000;

export const STATUS_JID = 'status@broadcast';
/** WhatsApp shows a status for 24 h after it was posted. */
export const STATUS_TTL_MS = 24 * 60 * 60 * 1000;
/** The message types a status can be (the rest of status@broadcast is protocol noise). */
export const STATUS_MESSAGE_TYPES: ReadonlySet<string> = new Set([
  'TEXT',
  'IMAGE',
  'VIDEO',
  'AUDIO',
]);

export const LIST_DEFAULT_LIMIT = 50;
export const LIST_MAX_LIMIT = 200;

/** Publishing (the same limits as the NAS fork's publishStatus). */
export const STATUS_RECIPIENTS_MAX = 256;
export const STATUS_TEXT_MAX_CHARS = 4096;
export const STATUS_CAPTION_MAX_CHARS = 1024;
export const STATUS_IMAGE_MAX_BYTES = 10 * 1024 * 1024;
export const STATUS_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set(['image/jpeg', 'image/png']);
export const STATUS_FONT_MIN = 1;
export const STATUS_FONT_MAX = 5;

export type StatusSource = 'live' | 'history' | 'connector' | 'backfill';

export function isStatusJid(jid: string | null | undefined): boolean {
  return stripAccountKey(String(jid || '')) === STATUS_JID;
}

export function isChannelJid(jid: string | null | undefined): boolean {
  return /^\d+@newsletter$/.test(stripAccountKey(String(jid || '')));
}

/** WA_STATUS_PUBLISH_ENABLED=true; anything else (unset included) keeps publishing off. */
export function statusPublishEnabled(): boolean {
  return process.env.WA_STATUS_PUBLISH_ENABLED === 'true';
}

// ---------------------------------------------------------------------------
// HTTP bodies
// ---------------------------------------------------------------------------

function invalid(message: string): MessageMutationError {
  return new MessageMutationError(message, 400, 'invalid_request');
}

function optionalId(value: unknown, field: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string') throw invalid(`${field} must be a string`);
  const id = value.trim();
  if (id.length > 512) throw invalid(`${field} is too long`);
  return id || undefined;
}

function parseLimit(value: unknown): number {
  if (value === undefined || value === null) return LIST_DEFAULT_LIMIT;
  if (
    typeof value !== 'number' ||
    !Number.isInteger(value) ||
    value < 1 ||
    value > LIST_MAX_LIMIT
  ) {
    throw invalid(`limit must be an integer from 1 to ${LIST_MAX_LIMIT}`);
  }
  return value;
}

export interface TimeCursor {
  at: string;
  messageId: string;
}

/** The opaque keyset of both lists: base64url of {t, id}. */
export function encodeTimeCursor(cursor: TimeCursor): string {
  return Buffer.from(JSON.stringify({ t: cursor.at, id: cursor.messageId })).toString('base64url');
}

function decodeTimeCursor(value: string): TimeCursor {
  try {
    const parsed = JSON.parse(Buffer.from(value, 'base64url').toString('utf8'));
    if (
      parsed &&
      typeof parsed.t === 'string' &&
      Number.isFinite(Date.parse(parsed.t)) &&
      typeof parsed.id === 'string' &&
      parsed.id
    ) {
      return { at: parsed.t, messageId: parsed.id };
    }
  } catch {
    // fall through
  }
  throw invalid('cursor is not one this route returned');
}

function parseCursor(value: unknown): TimeCursor | undefined {
  const cursor = optionalId(value, 'cursor');
  return cursor ? decodeTimeCursor(cursor) : undefined;
}

export interface StatusListQuery {
  /** A contact (phone, jid or 1:1 conversation id): only its statuses. */
  contact?: string;
  /** Also statuses past their 24 h (kept for WA_STATUS_RETENTION_DAYS). */
  includeExpired: boolean;
  /** Also our own statuses (default true). */
  includeOwn: boolean;
  limit: number;
  cursor?: TimeCursor;
}

/** {contact?, includeExpired?, includeOwn?, limit?, cursor?} of POST /statuses; 400 otherwise. */
export function parseStatusListQuery(body: Record<string, unknown>): StatusListQuery {
  for (const flag of ['includeExpired', 'includeOwn']) {
    if (body[flag] !== undefined && body[flag] !== null && typeof body[flag] !== 'boolean') {
      throw invalid(`${flag} must be a boolean`);
    }
  }
  const cursor = parseCursor(body.cursor);
  const contact = optionalId(body.contact ?? body.conversationId, 'contact');
  return {
    ...(contact ? { contact } : {}),
    includeExpired: body.includeExpired === true,
    includeOwn: body.includeOwn !== false,
    limit: parseLimit(body.limit),
    ...(cursor ? { cursor } : {}),
  };
}

export interface ChannelPostsQuery {
  /** `<digits>@newsletter`; all followed channels when absent. */
  channelId?: string;
  limit: number;
  cursor?: TimeCursor;
}

/** {channelId?, limit?, cursor?} of POST /channels/posts; 400 otherwise. */
export function parseChannelPostsQuery(body: Record<string, unknown>): ChannelPostsQuery {
  const channelId = optionalId(body.channelId ?? body.conversationId, 'channelId');
  if (channelId && !isChannelJid(channelId)) {
    throw invalid('channelId must be a channel jid (<digits>@newsletter)');
  }
  const cursor = parseCursor(body.cursor);
  return {
    ...(channelId ? { channelId: stripAccountKey(channelId) } : {}),
    limit: parseLimit(body.limit),
    ...(cursor ? { cursor } : {}),
  };
}

export interface StatusPublishRequest {
  type: 'text' | 'image';
  /** Text of a text status, caption of an image one. */
  text?: string;
  /** Image status: an http(s) URL the connector fetches. */
  url?: string;
  /** Normalised user jids, deduplicated, in the order given. */
  recipients: string[];
  /** Text status only: #RRGGBB or #AARRGGBB. */
  backgroundColor?: string;
  /** Text status only: WhatsApp's font 1..5. */
  font?: number;
}

/**
 * One recipient: an E.164 phone (with or without '+') or a user jid
 * (`@s.whatsapp.net`, `@c.us`, `@lid`). Groups, broadcasts and channels are
 * not people. Returns the normalised jid (device suffix dropped).
 */
export function statusRecipientJid(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw invalid('recipients must be phone numbers or WhatsApp user jids');
  }
  const raw = stripAccountKey(value.trim());
  if (/^\+?\d[\d\s-]{6,24}$/.test(raw)) {
    const digits = raw.replace(/\D/g, '');
    if (digits.length < 8 || digits.length > 15) throw invalid(`Invalid phone: ${value}`);
    return `${digits}@s.whatsapp.net`;
  }
  const match = /^(\d{1,20})(?::\d{1,3})?@(s\.whatsapp\.net|c\.us|lid)$/.exec(raw);
  if (!match) throw invalid(`recipients must be people (phone or user jid), got ${value}`);
  const server = match[2] === 'c.us' ? 's.whatsapp.net' : match[2];
  return jidNormalizedUser(`${match[1]}@${server}`) || `${match[1]}@${server}`;
}

/**
 * {type, text?, url?, recipients[], backgroundColor?, font?, confirm: true}
 * of POST /statuses/publish; 400 otherwise. confirm must be literally true:
 * a status goes to every recipient at once.
 */
export function parseStatusPublishRequest(body: Record<string, unknown>): StatusPublishRequest {
  if (body.confirm !== true) {
    throw invalid('confirm must be true: a status goes to every recipient');
  }
  const type = body.type;
  if (type !== 'text' && type !== 'image') throw invalid("type must be 'text' or 'image'");
  if (!Array.isArray(body.recipients) || body.recipients.length === 0) {
    throw invalid('recipients must be a non-empty array (the audience is always explicit)');
  }
  if (body.recipients.length > STATUS_RECIPIENTS_MAX) {
    throw invalid(`recipients must not exceed ${STATUS_RECIPIENTS_MAX} entries`);
  }
  const recipients = [...new Set(body.recipients.map(statusRecipientJid))];
  if (body.text !== undefined && body.text !== null && typeof body.text !== 'string') {
    throw invalid('text must be a string');
  }
  const text = typeof body.text === 'string' && body.text.trim() ? body.text : undefined;
  if (type === 'text') {
    if (!text) throw invalid('text is required for a text status');
    if (text.length > STATUS_TEXT_MAX_CHARS) {
      throw invalid(`text must not exceed ${STATUS_TEXT_MAX_CHARS} characters`);
    }
    if (body.url !== undefined && body.url !== null)
      throw invalid('url is only for an image status');
    let backgroundColor: string | undefined;
    if (body.backgroundColor !== undefined && body.backgroundColor !== null) {
      if (
        typeof body.backgroundColor !== 'string' ||
        !/^#?(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(body.backgroundColor.trim())
      ) {
        throw invalid('backgroundColor must be a 6 or 8 digit hex colour');
      }
      const hex = body.backgroundColor.trim();
      backgroundColor = hex.startsWith('#') ? hex : `#${hex}`;
    }
    let font: number | undefined;
    if (body.font !== undefined && body.font !== null) {
      if (
        typeof body.font !== 'number' ||
        !Number.isInteger(body.font) ||
        body.font < STATUS_FONT_MIN ||
        body.font > STATUS_FONT_MAX
      ) {
        throw invalid(`font must be an integer from ${STATUS_FONT_MIN} to ${STATUS_FONT_MAX}`);
      }
      font = body.font;
    }
    return {
      type,
      text,
      recipients,
      ...(backgroundColor ? { backgroundColor } : {}),
      ...(font ? { font } : {}),
    };
  }
  if (typeof body.url !== 'string' || !/^https?:\/\/\S+$/i.test(body.url.trim())) {
    throw invalid('url must be an http(s) URL of the image');
  }
  if (text && text.length > STATUS_CAPTION_MAX_CHARS) {
    throw invalid(`text (caption) must not exceed ${STATUS_CAPTION_MAX_CHARS} characters`);
  }
  for (const field of ['backgroundColor', 'font']) {
    if (body[field] !== undefined && body[field] !== null) {
      throw invalid(`${field} is only for a text status`);
    }
  }
  return { type, url: body.url.trim(), recipients, ...(text ? { text } : {}) };
}

// ---------------------------------------------------------------------------
// DB
// ---------------------------------------------------------------------------

let tableMissingUntil = 0;
let missingTableLogged = false;

/** Test hook: forget the "table missing" state between cases. */
export function resetStatusStoreStateForTests(): void {
  tableMissingUntil = 0;
  missingTableLogged = false;
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function tableKnownMissing(): boolean {
  return tableMissingUntil > Date.now();
}

function noteTablePresent(): void {
  if (missingTableLogged) {
    missingTableLogged = false;
    console.info('whatsapp_statuses is available: statuses are indexed');
  }
  tableMissingUntil = 0;
}

/** 42P01 → noted, true; anything else → false (the caller decides). */
function tableMissing(error: unknown): boolean {
  if ((error as { code?: string } | null)?.code !== UNDEFINED_TABLE) return false;
  tableMissingUntil = Date.now() + MISSING_TABLE_RECHECK_MS;
  if (!missingTableLogged) {
    missingTableLogged = true;
    console.warn(
      'whatsapp_statuses does not exist yet (mcp-server migration 019 not applied): statuses ' +
        'still land in messages but are not indexed'
    );
  }
  return true;
}

export interface StatusInput {
  /** Bare or namespaced status id. */
  messageId: string;
  /** Bare, normalised author jid (messages.sender_wa_id without the prefix). */
  authorId: string;
  fromMe: boolean;
  messageType: string;
  postedAt: Date;
  source: StatusSource;
  audienceSize?: number;
  actor?: string;
}

/**
 * Index one status. A replay (history sync, the echo of our own publish)
 * never duplicates it; only the publish path ('connector') adds its audience
 * and actor to a row the echo may have written first. Never throws: false
 * when the table is missing, the input is not a status or the DB failed.
 */
export async function recordStatus(input: StatusInput): Promise<boolean> {
  const id = stripAccountKey(String(input.messageId || '').trim());
  const author = stripAccountKey(String(input.authorId || '').trim());
  const at = input.postedAt;
  if (
    !id ||
    !author ||
    isStatusJid(author) ||
    !STATUS_MESSAGE_TYPES.has(input.messageType) ||
    !(at instanceof Date) ||
    !Number.isFinite(at.getTime()) ||
    tableKnownMissing()
  ) {
    return false;
  }
  try {
    await getPool().query(
      `INSERT INTO whatsapp_statuses
         (account, wa_message_id, author_id, from_me, message_type, posted_at, expires_at,
          audience_size, source, actor)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
       ON CONFLICT (account, wa_message_id) DO UPDATE SET
         audience_size = COALESCE(EXCLUDED.audience_size, whatsapp_statuses.audience_size),
         actor = COALESCE(EXCLUDED.actor, whatsapp_statuses.actor),
         source = EXCLUDED.source,
         updated_at = now()
       WHERE EXCLUDED.source = 'connector'`,
      [
        connectorAccount(),
        accountKey(id),
        accountKey(author),
        input.fromMe,
        input.messageType,
        at,
        new Date(at.getTime() + STATUS_TTL_MS),
        input.audienceSize ?? null,
        input.source,
        input.actor || null,
      ]
    );
    noteTablePresent();
    return true;
  } catch (error) {
    if (!tableMissing(error))
      console.warn(`status index failed for ${id}: ${describeError(error)}`);
    return false;
  }
}

/**
 * The author ids (namespaced, as messages.sender_wa_id) a contact may have
 * posted under: its phone forms, and both sides of its PN ↔ LID aliases
 * (social_contact_aliases of 008, blocked evidence excluded).
 */
export async function contactAuthorIds(contactJid: string): Promise<string[]> {
  const candidates = externalIdCandidates(contactJid);
  if (!candidates.length) return [];
  const ids = new Set(candidates);
  try {
    const result = await getPool().query(
      `WITH canon AS (
         SELECT a.canonical_external_id AS id
           FROM social_contact_aliases a
          WHERE a.account_id = $1 AND a.evidence <> 'blocked'
            AND (a.alias_external_id = ANY($2::text[]) OR a.canonical_external_id = ANY($2::text[]))
       )
       SELECT id FROM canon
       UNION
       SELECT a.alias_external_id FROM social_contact_aliases a
        WHERE a.account_id = $1 AND a.evidence <> 'blocked'
          AND a.canonical_external_id IN (SELECT id FROM canon)`,
      [whatsappAccountId(), candidates]
    );
    for (const row of result.rows) {
      for (const id of externalIdCandidates(String(row.id))) ids.add(id);
    }
  } catch (error) {
    if ((error as { code?: string } | null)?.code !== UNDEFINED_TABLE) throw error;
  }
  return [...ids].map(id => accountKey(id));
}

function iso(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(value as string);
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

export interface StatusEntry {
  messageId: string;
  /** Where the media lives for GET /messages/media/:chatId/:msgId. */
  conversationId: typeof STATUS_JID;
  authorId: string;
  authorName: string | null;
  fromMe: boolean;
  messageType: string | null;
  text: string | null;
  hasMedia: boolean;
  mimeType: string | null;
  postedAt: string;
  expiresAt: string;
  active: boolean;
  audienceSize: number | null;
  source: StatusSource;
}

export interface StatusList {
  statuses: StatusEntry[];
  nextCursor: string | null;
  persisted: boolean;
}

/**
 * Statuses of the account, newest first: still visible (24 h) unless
 * includeExpired, optionally of one author (`authorIds`, namespaced), our own
 * unless includeOwn is false. A revoked status (messages.is_deleted) is left
 * out, as WhatsApp drops it.
 */
export async function listStatuses(options: {
  authorIds?: string[];
  includeExpired: boolean;
  includeOwn: boolean;
  limit: number;
  cursor?: TimeCursor;
  now?: Date;
}): Promise<StatusList> {
  if (tableKnownMissing()) return { statuses: [], nextCursor: null, persisted: false };
  const now = options.now || new Date();
  const params: unknown[] = [connectorAccount()];
  const filters = ['s.account = $1'];
  if (options.authorIds) {
    params.push(options.authorIds);
    filters.push(`s.author_id = ANY($${params.length}::text[])`);
  }
  if (!options.includeExpired) {
    params.push(now);
    filters.push(`s.expires_at > $${params.length}`);
  }
  if (!options.includeOwn) filters.push('NOT s.from_me');
  if (options.cursor) {
    params.push(options.cursor.at, accountKey(options.cursor.messageId));
    filters.push(
      `(s.posted_at, s.wa_message_id) < ($${params.length - 1}::timestamptz, $${params.length}::text)`
    );
  }
  params.push(options.limit + 1);
  try {
    const result = await getPool().query(
      `SELECT s.wa_message_id, s.author_id, s.from_me, s.posted_at, s.expires_at,
              s.audience_size, s.source,
              COALESCE(m.message_type, s.message_type) AS message_type, m.content,
              COALESCE(p.name, p.push_name) AS author_name,
              (SELECT a.mime_type FROM attachments a WHERE a.message_id = m.id
                ORDER BY a.id DESC LIMIT 1) AS mime_type,
              EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id) AS has_media
         FROM whatsapp_statuses s
         LEFT JOIN messages m ON m.wa_message_id = s.wa_message_id AND m.platform = 'whatsapp'
         LEFT JOIN participants p ON p.id = s.author_id
        WHERE ${filters.join(' AND ')}
          AND NOT COALESCE(m.is_deleted, FALSE)
        ORDER BY s.posted_at DESC, s.wa_message_id DESC
        LIMIT $${params.length}`,
      params
    );
    noteTablePresent();
    const rows = result.rows.slice(0, options.limit);
    const last = rows[rows.length - 1];
    return {
      statuses: rows.map(row => {
        const expiresAt = iso(row.expires_at) || '';
        return {
          messageId: stripAccountKey(String(row.wa_message_id)),
          conversationId: STATUS_JID,
          authorId: stripAccountKey(String(row.author_id)),
          authorName: row.author_name ?? null,
          fromMe: !!row.from_me,
          messageType: row.message_type ?? null,
          text: row.content ?? null,
          hasMedia: !!row.has_media,
          mimeType: row.mime_type ?? null,
          postedAt: iso(row.posted_at) || '',
          expiresAt,
          active: Date.parse(expiresAt) > now.getTime(),
          audienceSize:
            row.audience_size === null || row.audience_size === undefined
              ? null
              : Number(row.audience_size),
          source: row.source as StatusSource,
        };
      }),
      nextCursor:
        result.rows.length > options.limit && last
          ? encodeTimeCursor({
              at: iso(last.posted_at) || '',
              messageId: stripAccountKey(String(last.wa_message_id)),
            })
          : null,
      persisted: true,
    };
  } catch (error) {
    if (tableMissing(error)) return { statuses: [], nextCursor: null, persisted: false };
    throw error;
  }
}

export interface ChannelPost {
  messageId: string;
  channelId: string;
  /** null while the channel has no real name stored (its conversation is named by its jid). */
  channelName: string | null;
  messageType: string | null;
  text: string | null;
  hasMedia: boolean;
  mimeType: string | null;
  postedAt: string;
  /** POLL / EVENT etc. as messages.metadata carries them. */
  structured?: Record<string, unknown>;
}

export interface ChannelPostList {
  posts: ChannelPost[];
  nextCursor: string | null;
  /** Channels of this account the posts were read from. */
  channels: number;
}

/**
 * The channel conversations of this account (namespaced ids), all of them or
 * one. From `conversations` (a few thousand rows), never a scan of messages.
 */
async function channelConversationIds(channelId?: string): Promise<string[]> {
  const result = await getPool().query(
    `SELECT id FROM conversations
      WHERE account_id = $1 AND merged_into IS NULL
        AND ${channelId ? 'external_id = $2' : "external_id LIKE '%@newsletter'"}`,
    channelId ? [whatsappAccountId(), channelId] : [whatsappAccountId()]
  );
  return result.rows.map(row => String(row.id));
}

/**
 * The id a channel post lives under in `messages`. A channel's message ids
 * are only unique inside the channel, while `messages.wa_message_id` is one
 * key per account and the insert is ON CONFLICT DO NOTHING: the post of a
 * second channel whose id another channel already holds would vanish without
 * a trace, and its message key would overwrite the first post's. The first
 * channel keeps the bare id (every stored row, key and revoke stays as it is);
 * a clash with another channel's row gets `<channel jid>:<id>`. The ingest and
 * the revoke / edit that names the post ask with the same (channel, id), so
 * both reach the same row. A failed lookup answers the bare id: it never
 * stops the ingest.
 */
export async function channelPostMessageId(channelJid: string, id: string): Promise<string> {
  try {
    const result = await getPool().query(
      `SELECT conversation_id FROM messages WHERE wa_message_id = $1`,
      [accountKey(id)]
    );
    const holder = result.rows[0]?.conversation_id;
    return holder && holder !== accountKey(channelJid) ? `${channelJid}:${id}` : id;
  } catch {
    return id;
  }
}

/**
 * Posts of the channels this account receives (or of one), newest first,
 * from `messages`: the conversations of `<id>@newsletter`. A deleted post is
 * left out. Media: GET /messages/media/:channelId/:messageId.
 */
export async function listChannelPosts(query: ChannelPostsQuery): Promise<ChannelPostList> {
  const ids = await channelConversationIds(query.channelId);
  if (!ids.length) return { posts: [], nextCursor: null, channels: 0 };
  const params: unknown[] = [ids];
  const filters = ['m.conversation_id = ANY($1::text[])', "m.platform = 'whatsapp'"];
  if (query.cursor) {
    params.push(query.cursor.at, accountKey(query.cursor.messageId));
    filters.push(
      `(m.wa_timestamp, m.wa_message_id) < ($${params.length - 1}::timestamptz, $${params.length}::text)`
    );
  }
  params.push(query.limit + 1);
  const result = await getPool().query(
    `SELECT m.wa_message_id, m.conversation_id, m.message_type, m.content, m.wa_timestamp,
            m.metadata->'poll' AS poll, m.metadata->'event' AS event,
            c.name AS channel_name, c.external_id,
            (SELECT a.mime_type FROM attachments a WHERE a.message_id = m.id
              ORDER BY a.id DESC LIMIT 1) AS mime_type,
            EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id) AS has_media
       FROM messages m
       JOIN conversations c ON c.id = m.conversation_id
      WHERE ${filters.join(' AND ')}
        AND NOT COALESCE(m.is_deleted, FALSE)
      ORDER BY m.wa_timestamp DESC, m.wa_message_id DESC
      LIMIT $${params.length}`,
    params
  );
  const rows = result.rows.slice(0, query.limit);
  const last = rows[rows.length - 1];
  return {
    posts: rows.map(row => {
      const channelId = String(row.external_id || stripAccountKey(String(row.conversation_id)));
      const name = typeof row.channel_name === 'string' ? row.channel_name.trim() : '';
      const structured = {
        ...(row.poll ? { poll: row.poll } : {}),
        ...(row.event ? { event: row.event } : {}),
      };
      return {
        messageId: stripAccountKey(String(row.wa_message_id)),
        channelId,
        channelName: name && name !== channelId ? name : null,
        messageType: row.message_type ?? null,
        text: row.content ?? null,
        hasMedia: !!row.has_media,
        mimeType: row.mime_type ?? null,
        postedAt: iso(row.wa_timestamp) || '',
        ...(Object.keys(structured).length ? { structured } : {}),
      };
    }),
    nextCursor:
      result.rows.length > query.limit && last
        ? encodeTimeCursor({
            at: iso(last.wa_timestamp) || '',
            messageId: stripAccountKey(String(last.wa_message_id)),
          })
        : null,
    channels: ids.length,
  };
}
