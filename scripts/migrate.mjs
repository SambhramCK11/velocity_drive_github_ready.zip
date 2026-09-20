/**
 * Apply db/schema.sql to the Neon database in DATABASE_URL.
 *
 * Idempotent — every statement is CREATE ... IF NOT EXISTS — so re-running is
 * safe. The Flask app keeps using SQLite via app/database.py; this is only for
 * the Worker's Postgres.
 *
 *   npm run db:migrate
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { neon } from '@neondatabase/serverless';

import { ROOT, databaseUrl, splitStatements } from './db.mjs';

const sql = neon(databaseUrl());
const statements = splitStatements(readFileSync(resolve(ROOT, 'db/schema.sql'), 'utf8'));

console.log(`Applying ${statements.length} statement(s) from db/schema.sql...`);
for (const [index, statement] of statements.entries()) {
  try {
    await sql.query(statement);
    console.log(`  ${index + 1}/${statements.length}  ${statement.split('\n')[0].slice(0, 60)}`);
  } catch (error) {
    console.error(`\nFailed on statement ${index + 1}:\n${statement}\n`);
    throw error;
  }
}

const tables = await sql`
  SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public' ORDER BY table_name
`;
console.log(`\nMigration complete — ${tables.length} table(s): ${tables.map((t) => t.table_name).join(', ')}`);
