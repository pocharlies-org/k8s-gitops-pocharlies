# SC-2161 · criterios del 00-spec.md

- [ ] Una sesión de la compañía cuyo hilo principal O cualquiera de sus subagentes se queda sin cuota de Claude sigue trabajando en otra cuenta con cuota, sin intervención y sin perder el transcript. Respeta el modo de cuenta de SC-2066: la elegida primero, y después las demás.
- [ ] Si ninguna cuenta tiene cuota, aplica lo que ya hace SC-1880: el modelo de su fila sin Claude.
- [ ] Ningún agente se queda colgado por un subagente muerto por cuota: o se recupera, o se cierra y se reanuda.
- [ ] Se mide con un caso real, o forzado, en la compañía.
- [ ] Las sesiones en vivo (interactivas) quedan cubiertas si el diseño lo permite. Si no, se dice en una línea qué falta.
