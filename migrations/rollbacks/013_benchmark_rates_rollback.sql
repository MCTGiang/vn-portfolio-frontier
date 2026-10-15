-- Rollback migration 013: drop benchmark schema and 3 tables
DROP TABLE IF EXISTS benchmark.vn_bond_yield;
DROP TABLE IF EXISTS benchmark.sbv_policy_rate;
DROP TABLE IF EXISTS benchmark.bank_deposit_rate;
DROP SCHEMA IF EXISTS benchmark CASCADE;
