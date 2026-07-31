type LogLevel = 'debug' | 'info' | 'warn' | 'error';

type LogContext = {
  screen?: string;
  action?: string;
  userId?: string | null;
  receiptId?: string | number | null;
  requestId?: string | null;
  metadata?: Record<string, unknown>;
};

const enableClientLogs = (globalThis as any)?.process?.env?.EXPO_PUBLIC_ENABLE_CLIENT_LOGS === 'true';
const enabled = __DEV__ || enableClientLogs;
let reporting = false;

function sanitize(value: unknown): unknown {
  if (!value || typeof value !== 'object') return value;
  const copy: Record<string, unknown> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, entry]) => {
    if (/password|token|secret|authorization/i.test(key)) {
      copy[key] = '[redacted]';
    } else {
      copy[key] = entry;
    }
  });
  return copy;
}

function emit(level: LogLevel, message: string, context: LogContext = {}, error?: unknown) {
  if (!enabled && level !== 'error') return;
  const payload = {
    at: new Date().toISOString(),
    level,
    message,
    screen: context.screen,
    action: context.action,
    userId: context.userId,
    receiptId: context.receiptId,
    requestId: context.requestId,
    metadata: sanitize(context.metadata),
    error: error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : error,
  };
  const line = `[ReceiptAI:${level}] ${message}`;
  if (level === 'error') console.error(line, payload);
  else if (level === 'warn') console.warn(line, payload);
  else console.log(line, payload);
  if ((level === 'error' || level === 'warn') && !reporting) {
    reporting = true;
    const origin = String((globalThis as any)?.location?.origin || '').replace(/\/+$/, '');
    const configured = String((globalThis as any)?.process?.env?.EXPO_PUBLIC_API_URL || '').replace(/\/+$/, '');
    const endpoint = `${origin || configured || 'https://web-production-3605f4.up.railway.app'}/client-errors`;
    const errorDetails = error instanceof Error
      ? { error_type: error.name, stack: error.stack?.slice(0, 4000) }
      : {};
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        severity: level === 'warn' ? 'warning' : 'error',
        source: context.screen || 'app',
        message,
        request_id: context.requestId,
        metadata: sanitize({
          action: context.action,
          receiptId: context.receiptId,
          ...context.metadata,
        }),
        ...errorDetails,
      }),
    }).catch(() => {}).finally(() => { reporting = false; });
  }
}

export const appLogger = {
  debug: (message: string, context?: LogContext) => emit('debug', message, context),
  info: (message: string, context?: LogContext) => emit('info', message, context),
  warn: (message: string, context?: LogContext) => emit('warn', message, context),
  error: (message: string, error?: unknown, context?: LogContext) => emit('error', message, context, error),
};
