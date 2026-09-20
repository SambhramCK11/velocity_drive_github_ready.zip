/**
 * Business configuration — the values from app/config.py's BaseConfig.
 *
 * Kept in one place for the same reason the Python does: ranking weights and
 * pricing rules are tuned here, not scattered through the handlers. The values
 * must match app/config.py, and test/services.test.mjs checks the pricing that
 * depends on them against the Python.
 */

export const CONFIG = {
  COMPANY_NAME: 'Velocity Drive',
  COMPANY_CITY: 'Dubai',
  CURRENCY: 'AED',
  MIN_RENTAL_DAYS: 1,
  MAX_RENTAL_DAYS: 90,
  VAT_RATE: 0.05, // UAE VAT
  SECURITY_DEPOSIT: 1500.0,

  // Multi-day discount tiers: [minimum days, discount fraction], longest first.
  DISCOUNT_TIERS: [
    [30, 0.25],
    [7, 0.15],
    [3, 0.07],
  ],

  // Recommendation weights. These sum to 1.0 and are the single place to tune
  // ranking behaviour. Key order matters: the score is summed in this order so
  // the floating-point result matches the Python's exactly.
  RECOMMENDER_WEIGHTS: {
    semantic: 0.34, // TF-IDF cosine similarity on the car profile text
    budget: 0.24,   // how well the daily rate fits the stated budget
    capacity: 0.16, // seats vs. passengers
    category: 0.14, // explicit category / body-style preference
    features: 0.07, // requested feature coverage
    quality: 0.05,  // rating and popularity prior
  },
};
