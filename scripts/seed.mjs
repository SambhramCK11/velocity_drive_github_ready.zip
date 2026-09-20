/**
 * Load db/seed.sql — the eighteen-car fleet — into Neon.
 *
 * db/seed.sql is generated from app/seed.py's FLEET by
 * scripts/export-fleet.py, so the Worker and the Flask app describe the same
 * cars. Re-running adds nothing: each insert is ON CONFLICT DO NOTHING.
 *
 *   npm run db:seed
 *   npm run db:seed -- --force    # clear the fleet and reload
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { neon } from '@neondatabase/serverless';

import { ROOT, databaseUrl, splitStatements } from './db.mjs';

const sql = neon(databaseUrl());
const force = process.argv.includes('--force');

if (force) {
  // bookings and search_events reference cars, so clear them together.
  console.log('Clearing the existing fleet and its bookings...');
  await sql`TRUNCATE cars, bookings, customers, search_events RESTART IDENTITY CASCADE`;
}

const statements = splitStatements(readFileSync(resolve(ROOT, 'db/seed.sql'), 'utf8'));
for (const statement of statements) {
  await sql.query(statement);
}

const [counts] = await sql`
  SELECT (SELECT count(*)::int FROM cars)          AS cars,
         (SELECT count(DISTINCT category)::int FROM cars) AS categories,
         (SELECT count(*)::int FROM bookings)      AS bookings
`;
console.log(
  `Seed complete — ${counts.cars} cars across ${counts.categories} classes, ` +
    `${counts.bookings} booking(s).`
);
if (counts.cars === 0) {
  console.error('\nNo cars were inserted. Regenerate db/seed.sql with:');
  console.error('  python scripts/export-fleet.py > db/seed.sql');
  process.exit(1);
}
