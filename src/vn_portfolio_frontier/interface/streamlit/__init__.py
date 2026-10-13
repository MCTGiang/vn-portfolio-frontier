"""Streamlit UI layer (ADR-015 interface ring).

Entry point: `streamlit run src/vn_portfolio_frontier/interface/streamlit/app.py`

The interface ring consumes the AppFactory to wire the full dependency chain
(domain + application + infrastructure) and renders user-facing views. It must
not import from infrastructure directly (lint-imports enforced).
"""
