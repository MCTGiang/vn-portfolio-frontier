# ADR-015 — Hexagonal Architecture + Strategy + Repository + Template Method cho Feature 2

- **Status**: Accepted
- **Date**: 2026-10-02
- **Deciders**: Mai Công Trà Giang (student lead)
- **Supersedes**: — (new, chuẩn hóa cho F2+)
- **Related**: ADR-013 (Streamlit UI), ADR-014 (Bronze/Silver schema)
- **Course references**: IT4490 L4 Architecture, L8-9 Design Patterns · IT3120 L7 Package Diagram

---

## 1. Context — Bối cảnh

Project 1 (Efficient Frontier) được viết dưới dạng script monolithic Streamlit:
business logic, data loading, UI rendering đan xen trong vài file lớn. Code chạy
được nhưng:

- Unit test chỉ cover 23% logic (vì tach business logic khỏi `st.*` calls rất khó)
- Thêm một chiến lược rebalance mới sẽ phải sửa 4-5 file khác nhau
- Chuyển DB từ CSV sang Neon đòi hỏi sửa toàn bộ layer đọc data
- Mocking vnstock API cho test = patch nested import, fragile

Feature 2 (Rebalancing Simulator) có yêu cầu mức complexity cao hơn:

- **4 chiến lược rebalance**: ThresholdBand, CalendarMonthly, FixedWindow, Hybrid
  (Sprint 11 MUST tier = 1 chiến lược; Sprint 12 SHOULD tier = thêm 3)
- **Sensitivity sweep** chạy cùng 1 chiến lược trên grid tham số (10×10 points)
- **Persistence** vào Neon schema `simulation.*` (rebalance_run, decision, sensitivity_grid)
- **Dry-run mode** preview orders mà không commit
- **Decomposition** output: return attribution theo asset × factor × period
- **Cost model** gồm brokerage % + slippage bps + tax short-term

Nếu tiếp tục pattern Project 1, Feature 2 sẽ:

- Test coverage dự kiến < 30% (committee không chấp nhận cho thesis)
- Thêm chiến lược thứ 5 (volatility-based ở sprint sau) phải refactor lớn
- Migrate F1 vào kiến trúc chung lúc tích hợp thesis (chương 8) sẽ phải viết lại

**Cần một kiến trúc:**

1. Tách rõ **business logic** khỏi **I/O** (DB, API, UI)
2. Cho phép **unit test** domain logic không cần DB thật
3. **Extensible**: thêm strategy mới = 1 class implement interface, không chạm core
4. **Reusable**: F1 Frontier và F3 News Sentiment share chung infrastructure layer
5. Phù hợp **scope thesis** — không over-engineer bằng cả Clean Architecture full-stack

---

## 2. Decision — Quyết định

Áp dụng **Hexagonal Architecture (Ports & Adapters)** của Alistair Cockburn
(2005), kết hợp 3 design pattern GoF: **Strategy**, **Repository**, **Template Method**.

### 2.1 Hexagonal Architecture

Chia code thành 4 ring, dependency chỉ đi hướng **vào trong**:

```
┌─────────────────────────────────────────────────┐
│  Interface  (Streamlit pages, CLI entry points) │
├─────────────────────────────────────────────────┤
│  Application  (Use case orchestrators)          │
├─────────────────────────────────────────────────┤
│  Domain  (Entities + Strategies + Services)     │  ← pure Python, no I/O
├─────────────────────────────────────────────────┤
│  Infrastructure  (DB repos, vnstock adapter)    │
└─────────────────────────────────────────────────┘
                   ↑ ↑ ↑
         External: Neon · vnstock · PhoBERT model
```

**Rule bắt buộc:**

- `domain/` KHÔNG được import từ `infrastructure/`, `application/`, `interface/`
- `application/` chỉ import từ `domain/` và từ **ports** (abstract interfaces)
- `infrastructure/` implement các ports do `application/` khai báo
- `interface/` orchestrate `application/` services

Thực thi bằng pre-commit hook `import-linter` với contracts:
```ini
[importlinter:contract:1]
name = Domain purity
type = forbidden
source_modules = vn_portfolio_frontier.domain
forbidden_modules = vn_portfolio_frontier.infrastructure, vn_portfolio_frontier.interface
```

### 2.2 Strategy Pattern — RebalanceStrategy

Interface chung cho mọi chiến lược rebalance:

```python
# domain/strategies/base.py
from typing import Protocol
from datetime import date

class RebalanceStrategy(Protocol):
    name: str

    def should_trigger(
        self,
        current: Portfolio,
        target_weights: dict[str, float],
        context: RebalanceContext,
    ) -> bool: ...

    def compute_target_weights(
        self,
        current: Portfolio,
        context: RebalanceContext,
    ) -> dict[str, float]: ...
```

4 concrete classes trong `domain/strategies/`:

| Class | Trigger logic |
|---|---|
| `ThresholdBandStrategy` | abs(weight_i - target_i) > band_bps |
| `CalendarMonthlyStrategy` | context.date.day == rebalance_day (default: 1) |
| `FixedWindowStrategy` | days_since_last_rebalance >= window_days |
| `HybridStrategy` | ThresholdBand AND (CalendarMonthly OR FixedWindow) |

### 2.3 Template Method — BaseStrategy.rebalance()

Common flow dùng cho mọi strategy:

```python
# domain/strategies/base.py
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """Template Method base class. Subclass override 2 hook methods."""

    def __init__(self, cost_calculator: CostCalculator):
        self._cost_calculator = cost_calculator

    def rebalance(self, current: Portfolio, context: RebalanceContext) -> RebalanceDecision:
        """Template method — không override."""
        target = self.compute_target_weights(current, context)   # ← hook
        if not self.should_trigger(current, target, context):     # ← hook
            return RebalanceDecision.no_action(reason="no_trigger")
        orders = self._compute_orders(current, target, context)
        costs = self._cost_calculator.compute(orders, context)
        return RebalanceDecision(
            orders=orders,
            costs=costs,
            strategy_name=self.name,
            triggered_at=context.date,
        )

    @abstractmethod
    def compute_target_weights(...): ...  # ← subclass fill

    @abstractmethod
    def should_trigger(...): ...           # ← subclass fill

    def _compute_orders(self, current, target, context):
        """Shared logic — chuyển weight delta → BUY/SELL orders tính theo shares."""
        # ... (common impl)
```

**Lợi ích Template Method ở đây:**

- Chống "copy-paste 4 lần" cho _compute_orders() và cost application
- Order semantics (round lot, min trade size) nhất quán giữa các strategy
- Dễ thêm cross-cutting concern (ví dụ logging mỗi decision) chỉ ở 1 chỗ

### 2.4 Repository Pattern — Data access

Mỗi aggregate root có 1 repository interface trong `application/ports/`:

```python
# application/ports/price_repository.py
from typing import Protocol
from datetime import date

class PriceRepository(Protocol):
    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[DailyPrice]: ...
    def get_latest_dates(self) -> dict[str, date]: ...
    def batch_insert(self, records: list[DailyPrice]) -> int: ...
```

Implement trong `infrastructure/repositories/`:

```python
# infrastructure/repositories/neon_price_repository.py
class NeonPriceRepository:  # satisfies PriceRepository
    def __init__(self, pool: psycopg_pool.ConnectionPool):
        self._pool = pool

    def get_ohlcv(self, ticker, start, end):
        with self._pool.connection() as conn:
            # ... SQL
```

**Danh sách Repository cho F2 (Sprint 11+):**

| Repository | Backing store | Used by |
|---|---|---|
| `PriceRepository` | Neon `prices.daily_ohlcv` | F1 Frontier, F2 Simulator |
| `RebalanceRunRepository` | Neon `simulation.rebalance_run` | F2 Simulator |
| `RebalanceDecisionRepository` | Neon `simulation.rebalance_decision` | F2 Simulator |
| `SensitivityGridRepository` | Neon `simulation.sensitivity_grid` | F2 Sensitivity Sweep |
| `FundamentalsRepository` | Neon `fundamentals.*` | F1 Frontier (constraints) |
| `NewsArticleRepository` | Neon `news_sentiment.article` | F3 (Sprint 13+) |

### 2.5 Dependency Injection — Factory function

Không dùng DI framework (overkill cho scope thesis). Dùng 1 factory function
wire tất cả deps:

```python
# application/factory.py
def make_rebalance_simulator(
    config: Settings,
    strategy_name: str = "threshold_band",
) -> RebalanceSimulator:
    pool = psycopg_pool.ConnectionPool(config.neon_dsn)
    price_repo = NeonPriceRepository(pool)
    run_repo = NeonRebalanceRunRepository(pool)
    decision_repo = NeonRebalanceDecisionRepository(pool)
    cost_calc = CostCalculator(
        brokerage_pct=config.brokerage_pct,
        slippage_bps=config.slippage_bps,
        tax_short_term_pct=config.tax_short_term_pct,
    )
    strategy = {
        "threshold_band": ThresholdBandStrategy(cost_calc, band_bps=config.band_bps),
        "calendar_monthly": CalendarMonthlyStrategy(cost_calc, day=config.rebalance_day),
        "fixed_window": FixedWindowStrategy(cost_calc, window_days=config.window_days),
        "hybrid": HybridStrategy(cost_calc, ...),
    }[strategy_name]
    return RebalanceSimulator(
        price_repo=price_repo,
        run_repo=run_repo,
        decision_repo=decision_repo,
        strategy=strategy,
    )
```

Test code có thể bypass factory, inject fake repos trực tiếp:

```python
# tests/unit/test_simulator.py
def test_threshold_band_triggers_at_5pct_drift():
    simulator = RebalanceSimulator(
        price_repo=FakeInMemoryPriceRepo(...),
        run_repo=FakeInMemoryRunRepo(),
        decision_repo=FakeInMemoryDecisionRepo(),
        strategy=ThresholdBandStrategy(FakeCostCalc(), band_bps=500),
    )
    result = simulator.run(portfolio=..., period=...)
    assert result.decisions[0].strategy_name == "threshold_band"
```

---

## 3. Structure — Cây thư mục cuối

```
src/vn_portfolio_frontier/
├── domain/                              # pure Python, ZERO I/O imports
│   ├── __init__.py
│   ├── entities/
│   │   ├── portfolio.py                 # Portfolio (aggregate root)
│   │   ├── holding.py                   # Holding (value object)
│   │   ├── rebalance_decision.py        # RebalanceDecision
│   │   ├── order.py                     # Order (Buy/Sell)
│   │   ├── daily_price.py               # DailyPrice (value object)
│   │   └── rebalance_context.py         # RebalanceContext (dates, cash, flags)
│   ├── strategies/
│   │   ├── base.py                      # BaseStrategy (Template Method)
│   │   ├── threshold_band.py            # Sprint 11 MUST
│   │   ├── calendar_monthly.py          # Sprint 12
│   │   ├── fixed_window.py              # Sprint 12
│   │   └── hybrid.py                    # Sprint 12
│   ├── services/
│   │   ├── cost_calculator.py           # CostCalculator (pure)
│   │   ├── return_decomposer.py         # ReturnDecomposer (attribution)
│   │   └── validator.py                 # InputValidator
│   └── errors.py                        # Domain exceptions
├── application/
│   ├── ports/                           # Port interfaces (Protocol)
│   │   ├── price_repository.py
│   │   ├── run_repository.py
│   │   ├── decision_repository.py
│   │   ├── sensitivity_grid_repository.py
│   │   ├── fundamentals_repository.py
│   │   └── news_article_repository.py
│   ├── services/
│   │   ├── rebalance_simulator.py       # Main use case orchestrator
│   │   ├── sensitivity_sweeper.py       # UC-F2-02
│   │   ├── dry_run_service.py           # UC-F2-03
│   │   ├── run_history_service.py       # UC-F2-04
│   │   └── run_comparator.py            # UC-F2-05
│   └── factory.py                       # Dependency wiring
├── infrastructure/                      # Adapters
│   ├── repositories/
│   │   ├── neon_price_repository.py
│   │   ├── neon_run_repository.py
│   │   ├── neon_decision_repository.py
│   │   ├── neon_sensitivity_grid_repository.py
│   │   ├── neon_fundamentals_repository.py
│   │   └── neon_news_article_repository.py
│   ├── adapters/
│   │   ├── vnstock_price_adapter.py     # fetch delta OHLCV
│   │   ├── vnstock_fundamentals_adapter.py
│   │   └── news_crawler_adapter.py
│   ├── config/
│   │   └── settings.py                  # Pydantic Settings from env
│   └── migrations/
│       └── 004_simulation_schema.sql    # Sprint 11 Task 1
├── interface/
│   ├── streamlit/
│   │   ├── app.py                       # Main entry
│   │   ├── pages/
│   │   │   ├── 01_frontier.py           # F1
│   │   │   ├── 02_rebalance_simulator.py  # F2
│   │   │   ├── 03_sensitivity.py
│   │   │   ├── 04_run_history.py
│   │   │   ├── 05_run_comparison.py
│   │   │   └── 06_news_sentiment.py     # F3
│   │   └── components/
│   │       ├── universe_selector.py     # UC-DL-04
│   │       ├── coverage_heatmap.py      # UC-DL-05
│   │       └── toast.py
│   └── cli/
│       └── sync_prices.py               # UC-DL-01 standalone invocation
└── shared/
    ├── logging.py
    └── errors.py
```

---

## 4. Consequences — Hệ quả

### 4.1 Positive

- **Testability**: Domain layer test được 100% không cần Neon/vnstock. Mock
  Repository, inject vào service, assert decisions. Mục tiêu test coverage
  domain + application ≥ 85% (Sprint 11 KPI).
- **Extensibility**: Thêm strategy mới (vd volatility-based ở Sprint 14) =
  1 file `domain/strategies/volatility_based.py` + 1 entry trong factory. Zero
  touch core.
- **Swap-ability**: Nếu đổi Neon → DuckDB (local dev), chỉ cần
  `DuckDBPriceRepository`. Domain + Application không biết.
- **Reusability**: F1 Frontier và F3 Sentiment dùng chung Repository layer. F3
  thêm `NewsArticleRepository` không ảnh hưởng F1/F2.
- **Thesis defense**: Kiến trúc chuẩn công nghiệp, trả lời được câu hỏi
  committee về SoC, DIP, testability. Reference được tới sách giáo trình
  IT4490 L4 + L8-9 + Clean Architecture (Uncle Bob).

### 4.2 Negative

- **File count tăng ~15x**: Project 1 có 8 file Python; F2 Hexagonal sẽ có
  ~60 file. Learning curve cho người join sau cao hơn.
- **Boilerplate**: Mỗi Port interface + 1 Adapter impl + 1 Fake test impl =
  3 file cho mỗi data source.
- **Manual wiring**: Không có DI container → factory function phải update
  mỗi khi thêm dep. Rủi ro quên inject khi scale.
- **Over-abstraction risk**: Nếu không kỷ luật, Repository chỉ wrap SQL
  2 dòng = cost cao hơn lợi. **Mitigation**: Chỉ tạo Repository cho aggregate
  root, không cho mỗi table.

### 4.3 Mitigations

- **Convention over config**: Folder structure cố định, naming cố định
  (`*_repository.py`, `*_adapter.py`, `*_service.py`). Grep được dễ.
- **import-linter contract** chạy ở pre-commit: catch violation sớm.
- **Factory function duy nhất** ở `application/factory.py`: tất cả wiring
  tập trung 1 chỗ, dễ audit.
- **Decision log mỗi khi thêm Repository**: ADR-016, ADR-017 nếu thêm pattern.

---

## 5. Alternatives considered — Phương án khác đã cân nhắc

### 5.1 Giữ pattern Project 1 (monolithic script)
**Rejected** vì:
- Test coverage không đạt (< 30% dự kiến)
- Thêm strategy mới = refactor lớn
- Committee sẽ chỉ trích thiếu kiến trúc

### 5.2 Layered Architecture 3-tier (Presentation → Business → Data)
**Rejected** vì:
- Không enforce Dependency Inversion Principle — Business layer
  thường vẫn import DB client trực tiếp
- Khó test logic business nếu DB layer dùng ORM với side effects
- Có đủ tất cả nhược điểm của Hexagonal nhưng không có lợi thế test-first

### 5.3 Clean Architecture full-stack (Uncle Bob — Entities → Use Cases → Controllers → Frameworks)
**Rejected** vì:
- Overkill cho scope thesis: 4 layer thay vì 4 ring, mỗi layer có
  interface riêng → file count x2 so với Hexagonal
- Use Case object per UC = 10 class rỗng cho F2 (5 UC) + F1 + F3
- Không mang lại lợi ích đo được so với Hexagonal ở scope này

**Hexagonal là subset gọn nhất của Clean Architecture đủ dùng.**

### 5.4 Vertical Slice Architecture (feature-first folders)
**Considered** nhưng rejected vì:
- 3 feature chia sẻ Repository + domain entities (Portfolio, Price,
  CostCalculator) → nếu vertical slice sẽ phải duplicate hoặc tạo shared
  folder giống hệt horizontal
- Thesis cần đồ hình layered rõ ràng cho Package Diagram chương 7

---

## 6. Implementation plan — Lộ trình áp dụng

| Sprint | Scope |
|---|---|
| **11** (06/10-19/10) | Build skeleton: `domain/`, `application/`, `infrastructure/` cho F2 MUST tier. Chỉ 1 strategy (ThresholdBand) + 1 cost model. 7 unit tests. |
| **12** (20/10-02/11) | Thêm 3 strategy (CalendarMonthly, FixedWindow, Hybrid) + Sensitivity Sweeper. Target domain test coverage 85%. |
| **12.5** | Migrate F1 Frontier vào `application/frontier_service.py`, reuse PriceRepository + FundamentalsRepository. |
| **13-15** | Build F3 Sentiment dùng chung infrastructure layer. Thêm NewsCrawlerAdapter + PhoBERTAdapter. |

---

## 7. Compliance checklist — Pre-merge gate cho PR

- [ ] `import-linter` pass (domain purity + application → infra forbidden)
- [ ] Mỗi `domain/strategies/*.py` có test riêng ≥ 1 unit test
- [ ] Mỗi `infrastructure/repositories/*.py` có integration test (optional nếu
      đã có contract test)
- [ ] Factory function cập nhật nếu thêm dep
- [ ] Diagram update: Package Diagram chương 7 nếu thêm layer

---

## 8. References — Tham chiếu

### Course material
- **IT4490** L4 Architectural Design · L8 Design Patterns · L9 Advanced Patterns
- **IT3120** L7 Package Diagram · L8 Component Diagram

### External
- Cockburn, A. (2005). *Hexagonal Architecture*. https://alistair.cockburn.us/hexagonal-architecture/
- Gamma, Helm, Johnson, Vlissides (1994). *Design Patterns: Elements of Reusable OO Software* — Strategy (Ch.5), Template Method (Ch.5)
- Fowler, M. (2003). *Patterns of Enterprise Application Architecture* — Repository (p.322)
- Martin, R. (2017). *Clean Architecture* — Dependency Rule (Ch.22)
- Vernon, V. (2013). *Implementing Domain-Driven Design* — Hexagonal reference impl (Ch.4)

### Project ADRs
- ADR-013 (2026-07): Streamlit as primary UI
- ADR-014 (2026-09): Bronze/Silver schema separation on Neon
- ADR-016 (TBD Sprint 11.5): Testing strategy (unit vs integration vs E2E split)
