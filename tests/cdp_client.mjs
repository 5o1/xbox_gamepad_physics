/** Small Chrome DevTools Protocol client with bounded RPCs and clean failure. */

export async function connectCdp(webSocketUrl, {
  timeoutMs = 20_000,
  WebSocketImpl = globalThis.WebSocket,
} = {}) {
  if (!WebSocketImpl) throw new Error('This Node.js runtime does not provide WebSocket');

  const socket = new WebSocketImpl(webSocketUrl);
  await new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      clearTimeout(timer);
      socket.removeEventListener('open', onOpen);
      socket.removeEventListener('error', onError);
      socket.removeEventListener('close', onClose);
    };
    const finish = (callback, event, closeSocket = false) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (closeSocket) {
        try { socket.close(); } catch {}
      }
      callback(event);
    };
    const onOpen = event => finish(resolve, event);
    const onError = () => finish(reject, new Error('CDP WebSocket failed to open'), true);
    const onClose = event => finish(
      reject,
      new Error(`CDP WebSocket closed before opening (${event.code ?? 'unknown'})`),
    );
    const timer = setTimeout(
      () => finish(
        reject,
        new Error(`CDP WebSocket open timeout after ${timeoutMs} ms`),
        true,
      ),
      timeoutMs,
    );
    socket.addEventListener('open', onOpen);
    socket.addEventListener('error', onError);
    socket.addEventListener('close', onClose);
  });

  let sequence = 0;
  let closed = false;
  const pending = new Map();
  const listeners = new Set();
  const rejectPending = reason => {
    for (const {reject, timer} of pending.values()) {
      clearTimeout(timer);
      reject(reason);
    }
    pending.clear();
  };

  socket.addEventListener('message', event => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      rejectPending(new Error(`Invalid CDP JSON: ${error.message}`));
      return;
    }
    if (message.id !== undefined) {
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      clearTimeout(request.timer);
      if (message.error) request.reject(new Error(`CDP ${request.method}: ${JSON.stringify(message.error)}`));
      else request.resolve(message.result);
      return;
    }
    for (const listener of listeners) listener(message);
  });
  socket.addEventListener('error', () => {
    rejectPending(new Error('CDP WebSocket error'));
  });
  socket.addEventListener('close', event => {
    closed = true;
    rejectPending(new Error(`CDP WebSocket closed (${event.code ?? 'unknown'})`));
  });

  function call(method, params = {}, {timeout = timeoutMs} = {}) {
    if (closed || socket.readyState !== WebSocketImpl.OPEN) {
      return Promise.reject(new Error(`Cannot call ${method}: CDP WebSocket is not open`));
    }
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`CDP timeout after ${timeout} ms: ${method}`));
      }, timeout);
      pending.set(id, {method, resolve, reject, timer});
      try {
        socket.send(JSON.stringify({id, method, params}));
      } catch (error) {
        clearTimeout(timer);
        pending.delete(id);
        reject(error);
      }
    });
  }

  function onEvent(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function close() {
    if (closed) return;
    closed = true;
    rejectPending(new Error('CDP client closed'));
    socket.close();
  }

  return {call, close, onEvent, socket};
}

export async function closeCdpTarget(baseUrl, targetId, {
  timeoutMs = 20_000,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!targetId) throw new Error('Cannot close a CDP target without an id');
  const endpoint = new URL(`/json/close/${encodeURIComponent(targetId)}`, baseUrl);
  const response = await fetchImpl(endpoint, {signal: AbortSignal.timeout(timeoutMs)});
  if (!response.ok) {
    throw new Error(`CDP target close failed: HTTP ${response.status}`);
  }
}

export async function evaluateCdp(client, expression, options = {}) {
  const {callTimeout, ...runtimeOptions} = options;
  const result = await client.call('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
    ...runtimeOptions,
  }, callTimeout === undefined ? {} : {timeout: callTimeout});
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text ?? 'Browser evaluation failed');
  }
  return result.result?.value;
}
