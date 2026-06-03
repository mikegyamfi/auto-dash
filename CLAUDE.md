# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Django 5.1 management system for a multi-branch car-wash business ("AutoDash"). Tracks customers/vehicles, services rendered, subscriptions, loyalty, commissions, expenses, sales targets, bookings, maintenance, and a daily worker scorecard. Heroku-deployable (see `Procfile`).

## Commands

A virtualenv lives at `.venv/`. Activate it before running anything:
- PowerShell: `.\.venv\Scripts\Activate.ps1`
- Bash: `source .venv/Scripts/activate`

Common commands (run from repo root, where `manage.py` lives):
- Install deps: `pip install -r requirements.txt`
- Dev server: `python manage.py runserver`
- Migrations: `python manage.py makemigrations` then `python manage.py migrate`
- Shell: `python manage.py shell`
- Create superuser: `python manage.py createsuperuser`
- Collect static (production): `python manage.py collectstatic --noinput`
- Run all tests: `python manage.py test autodash_App`
- Single test: `python manage.py test autodash_App.tests.test_revenue_consistency.RevenueConsistencyTest.test_revenue_matches_orders_today`

Custom management commands (`autodash_App/management/commands/`):
- `python manage.py seed_scorecard` — upsert scorecard categories/criteria from the spec; `--reset` wipes existing scorecards first.
- `python manage.py dedupe_revenue` — one-shot cleanup that drops duplicate `Revenue` rows per service order, keeping the oldest.

## Configuration

Settings use `python-decouple` and read from a `.env` file at repo root. Keys actually consumed:
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (comma-separated CSV)
- When `DEBUG=False`: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (Postgres via psycopg2)
- `SMS_API_KEY` — used by `autodash_App/helper.py` for the usmsgh SMS gateway

`DEBUG=True` uses the bundled `db.sqlite3`. Heroku `Procfile` runs `python manage.py migrate` on release and `gunicorn autodash_management.wsgi` for `web`.

**SMS is currently disabled in `views.py`** via local no-op shims around `send_sms` / `send_sms_club` (the imports from `.helper` are commented out). If re-enabling, restore the import and remove the stubs at the top of `autodash_App/views.py`.

## Architecture

Single Django project `autodash_management` with one app `autodash_App` doing essentially everything. All URLs live in `autodash_App/urls.py`; the project urlconf only mounts the app, the admin, and password-reset views.

### Auth & access control

- Custom user model: `autodash_App.CustomUser` (`AUTH_USER_MODEL`). Roles: `worker` or `customer`. Login is by `phone_number` (stored as `username` for workers — see `auth/auth_views.py`).
- `CustomUser.approved` gates login; unapproved users are bounced from `login_page`.
- Workers have a `Worker` profile (`user.worker_profile`). A worker with `is_branch_admin=True` is a branch-level admin.
- `decorators.staff_or_branch_admin_required` (at repo root) is the standard gate for "elevated" views — allows `is_staff`/`is_superuser` OR branch admins. Use it for any new admin/branch-admin view rather than `@staff_member_required` alone.
- Branch scoping pattern in `views.py`: `_get_admin_branch(request)` and `_get_user_branch(request)`. Branch admins are forced to their own branch; staff/superusers can pick via `?branch_id=` / `?branch=`. Follow this pattern when adding branch-scoped reports — never trust `request.GET['branch_id']` for non-staff.

### Domain model (`autodash_App/models.py`, ~1300 lines)

Read this file early — almost all business logic lives here. Key clusters:

- **Org**: `Branch`, `Worker` (with branch + `is_branch_admin` flag), `WorkerCategory` (the `service_provider=True` flag gates commission eligibility), worker-onboarding side-tables (`WorkerEducation`, `WorkerEmployment`, `WorkerReference`, `WorkerGuarantor`).
- **Catalog**: `VehicleGroup`, `ServiceCategory`, `Service` (priced per `VehicleGroup`, M2M to `Branch`, carries `commission_rate` and `loyalty_points_earned`/`loyalty_points_required`), `ProductCategory`, `Product`, `ProductStockLog`.
- **Customer**: `Customer` (with `loyalty_points` and helpers `add_loyalty_points` / `apply_loyalty`), `CustomerVehicle`, `LoyaltyTransaction`.
- **Subscriptions**: `Subscription` (template), `CustomerSubscription` (per-customer instance with `used_amount` / `sub_amount_remaining`), plus `CustomerSubscriptionTrail` and `CustomerSubscriptionRenewalTrail` audit logs. Use `autodash_App.subscription.assert_unique_active_subscription` before creating.
- **The core transaction**: `ServiceRenderedOrder` is the central "ticket" — links a `Customer` (or walk-in fields), a `CustomerVehicle`, M2M of `Worker`s, payment breakdown (`cash_paid`, `momo_amount`, `subscription_amount_used`, `loyalty_points_used`), `status` (`pending`/`completed`/`canceled`/`onCredit`), and a discount. `ServiceRendered` is the line-item (one per service on the order, with `negotiated_price`). `Commission` rows are derived per-worker-per-line.
- **Revenue/money flow**: `Revenue` is the canonical "money received" record — one per completed `ServiceRenderedOrder` (or `OtherService`), kept in sync by signals (see below). `Arrears` tracks unpaid `onCredit` orders; `Arrears.mark_as_paid()` creates the corresponding `Revenue`. `Expense` + `DailyExpenseBudget` + `WeeklyBudget` + `RecurringExpense` cover outflow. `RecurringPaymentSetup` + `DailyPaymentTarget` model recurring bills with rollover of unpaid balances.
- **Targets**: `SalesTarget` (weekly/monthly per branch), `DailySalesTarget` (per branch per weekday), `WorkerDailyAdjustment` (per-worker bonus/deduction; `branch` auto-copied from the worker on save).
- **Walk-ins**: `ServiceRenderedOrder.is_walkin` + `walkin_*` fields cover unregistered customers — branch-admin/staff UIs always need to handle both `order.customer` and the walk-in fallback (`display_customer_name` / `display_vehicle_info` properties do this).
- **Bookings**: `CustomerBooking` (`booked` → `arrived` → `converted`); converting calls `mark_converted(order)` and links back to the `ServiceRenderedOrder`.
- **Other services & maintenance**: `OtherService` (non-catalog jobs that still produce `Revenue`), `MaintenanceLog` + `MaintenanceExpense`.
- **Scorecard**: `ScorecardCategory` (weights should sum to 1.0) → `ScorecardCriterion` (some `auto_source`'d from orders/services vs the worker's daily targets) → one `DailyScorecard` per worker per day with `DailyScoreEntry` rows. `DailyScorecard.recalc()` computes the weighted `final_score` in `[0,1]`. Logic lives in `autodash_App/scorecard/scorecard_views.py` (~750 lines).
- **Notifications**: `Notification` is branch-scoped (no per-user recipient). Workers/branch-admins see their own branch; superusers see all. Built by signals (see below) and surfaced via the `worker_notifications` context processor.

### Critical invariants enforced outside view code

These run automatically — be aware before touching `ServiceRenderedOrder` / `OtherService` / commission code.

- **`autodash_App/signals.py`**: `pre_save` snapshots old status; `post_save` on `ServiceRenderedOrder` upserts a `Revenue` row when status becomes `completed` and deletes it otherwise. Same pattern for `OtherService`. `CustomerBooking` and `MaintenanceLog` `post_save` create branch-scoped `Notification`s. If you change status transitions, this is what keeps `Revenue` in sync — don't write your own `Revenue.objects.create` in views.
- **`autodash_App/commission_util.allocate_commission(service_rendered, discount_factor=1)`**: idempotently distributes commission across workers on a `ServiceRendered` whose `worker_category.service_provider=True`. Wipes obsolete `Commission` rows and writes `service_rendered.commission_amount`. Call this (via `ServiceRendered.allocate_commission`) whenever workers, price, or discount on a line change — not by manually creating `Commission` rows.
- **`autodash_App/middleware.DailyTargetGenerationMiddleware`**: registered in `MIDDLEWARE`. On the first request of each day it generates `DailyPaymentTarget` rows from `RecurringPaymentSetup`, carrying forward any prior unpaid balance (overpayments become a negative `brought_forward` — i.e. a credit). Uses Django cache key `daily_payment_targets_done_<YYYY-MM-DD>` to dedupe. Don't add a second daily-init mechanism — extend this one.
- **`autodash_App/context_processors.worker_notifications`**: registered in `TEMPLATES.OPTIONS.context_processors`. Every template gets `notif_unread_count` / `notif_latest_unread` / `notif_has_unread` filtered by the user's branch (or all branches for superusers).

### Views and URLs

`autodash_App/views.py` is ~8900 lines and holds the bulk of view code (worker-side service logging, customer-side dashboard, all admin/branch-admin reports, exports, booking flow, maintenance flow, etc.). The split-out files `auth/auth_views.py` and `scorecard/scorecard_views.py` are the only ones populated; `customer/`, `worker/`, `services/` directories exist with empty `*_views.py` placeholders — don't assume new view code belongs there unless explicitly extracting.

URL convention: admin / branch-admin routes are namespaced under `elevated/` in `autodash_App/urls.py`. Customer-only routes live under `customer/`. The root `''` route is `views.home`, which is also re-aliased as `select_branch` and `admin_dashboard` at different paths — be careful when reverse-resolving.

### Templates and static

Templates live in `autodash_App/templates/`, configured via `TEMPLATE_DIR = BASE_DIR / 'autodash_App' / 'templates'` plus `APP_DIRS=True`. Layout fragments are in `templates/inc/` and `templates/layouts/`. Custom filters: `autodash_App/templatetags/custom_filters.py` and `auth_extras.py` — `settings.py` imports `custom_filters` at module load, so breaking that module breaks Django startup.

Static files: `autodash_App/static/` (dev) collected to `BASE_DIR/assets/` (prod), served via WhiteNoise's `CompressedManifestStaticFilesStorage`. Media uploads go to `BASE_DIR/media/`.

## Conventions worth following

- Money values are `FloatField` throughout (legacy choice — don't migrate to `Decimal` ad-hoc). The one exception is `commission_util.py`, which converts to `Decimal` internally with `ROUND_HALF_UP` for the actual split math.
- When mutating a `ServiceRenderedOrder`'s workers, line prices, or discount, re-run `allocate_commission` on each affected `ServiceRendered` rather than touching `Commission` directly.
- Don't bypass the `post_save` signal by writing to `Revenue` directly except in `Arrears.mark_as_paid()` (which already does the right thing) — use `ServiceRenderedOrder.status` transitions.
- New "elevated" pages should be gated with `staff_or_branch_admin_required` and scoped via `_get_admin_branch` for staff or the worker's own branch for branch admins.
- Phone numbers are stored without country code; the SMS helper prepends `233` (Ghana). Keep that convention if re-enabling SMS.
