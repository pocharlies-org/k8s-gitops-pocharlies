import Redis, { RedisOptions } from 'ioredis';

// SC-2185: a client pinned to a static REDIS_URL keeps its TCP connection to the
// old master's pod IP after a valkey sentinel failover; that pod becomes a
// read-only replica and every write fails with READONLY (reads keep working).
// When REDIS_SENTINELS (comma-separated host:port) and REDIS_MASTER_NAME are set,
// build an ioredis client in sentinel mode so it follows the promoted master.
// Without those variables the behaviour is byte-identical to `new Redis(url)`.
export function createRedisClient(url: string, options: RedisOptions = {}): Redis {
  const sentinelsRaw = process.env.REDIS_SENTINELS;
  const masterName = process.env.REDIS_MASTER_NAME;
  if (!sentinelsRaw || !masterName) {
    return new Redis(url, options);
  }
  // Sentinel mode ignores the URL, so carry its credentials and db over.
  const parsed = new URL(url);
  const sentinels = sentinelsRaw.split(',').map(entry => {
    const [host, port] = entry.trim().split(':');
    return { host, port: Number(port) || 26379 };
  });
  return new Redis({
    sentinels,
    name: masterName,
    username: decodeURIComponent(parsed.username) || undefined,
    password: decodeURIComponent(parsed.password) || undefined,
    db: Number(parsed.pathname.replace('/', '')) || 0,
    ...options,
  });
}
