/**
 * Neon connection.
 *
 * The HTTP driver is stateless — no pool to exhaust and no socket to leak
 * between invocations, which matters on Neon's free tier where connection slots
 * are limited and the compute suspends when idle.
 *
 * Rows come back as objects, not arrays: unlike the college system's templates,
 * these access columns by name (`car.daily_rate`), matching sqlite3.Row.
 */

import { neon } from '@neondatabase/serverless';

export function connect(databaseUrl) {
  if (!databaseUrl) {
    throw new Error('DATABASE_URL is not set. Run: npx wrangler secret put DATABASE_URL');
  }
  return neon(databaseUrl);
}
