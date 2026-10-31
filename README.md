# Liquor Store POS with M-Pesa STK Push

A Django + PostgreSQL point-of-sale for a liquor store, with an online shop and M-Pesa (Safaricom Daraja) STK push payments.

> **Status:** this code was written without being able to install Django in the build environment, so it has been syntax-checked but **not run**. Run the test suite first (step 6 below). Expect to fix small things on first run.

## What's included

| Area | What it does |
|---|---|
| **POS** (`/pos/`) | Touch-friendly sales screen: search, barcode scan (scanner types the code + Enter), cart, **cash**, **M-Pesa STK push** or **split** payment, age-check box, printable 80mm receipt |
| **Inventory** (`/inventory/`) | Products, categories, buying/selling price, stock levels, re-order levels and **low-stock alerts** (badge in the menu + reports), stock in/out with an audit trail |
| **Users & roles** | `Admin`, `Manager`, `Cashier`. Cashiers can only use the POS and see their own sales from today. Managers/Admins get inventory, reports, voids. Manage users in `/admin/` |
| **Reports** (`/reports/`) | Sales, profit, transactions, daily trend, top products, payment methods, channel, cashier, stock value, CSV export |
| **Online shop** (`/`) | 18+ age gate, search/categories, cart, guest checkout, pay with M-Pesa, live order status page. Staff see paid online orders under *Online orders* and mark them handed over/delivered |

### How payments stay correct
- Stock is **reserved when the sale is created**, so two buyers can't get the last bottle. If payment fails or is cancelled, stock is returned.
- A sale becomes **Paid only when Safaricom confirms** (callback, or a status query if the callback is slow).
- Callbacks are idempotent, check the amount, and are protected by a secret in the URL.
- If a customer approves *after* the sale was released, the system re-reserves stock if possible; otherwise it flags the sale **Needs review** so you can refund.
- Selling prices are whole shillings because STK push only accepts whole amounts.

## Setup

```bash
# 1. Python env
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. PostgreSQL
createdb liquorpos                                      # or use pgAdmin

# 3. Config
cp .env.example .env                                    # then edit DB_* and STORE_* values

# 4. Database tables
python manage.py makemigrations accounts inventory sales payments
python manage.py migrate

# 5. First users (+ optional demo products)
python manage.py createsuperuser
python manage.py seed_demo                              # optional: creates admin/manager/cashier + sample stock

# 6. Check it works, then run
python manage.py test
python manage.py runserver
```

Open `http://127.0.0.1:8000/` (shop) and `http://127.0.0.1:8000/accounts/login/` (staff).
`seed_demo` creates `admin / admin12345`, `manager / manager12345`, `cashier / cashier12345`. **Delete or change these before real use.**

In `/admin/`, set each staff member's **Role** (Cashier / Manager / Admin).

## M-Pesa: from nothing to taking real money

### A. Try it with no Safaricom account (offline demo)
Set `MPESA_SIMULATE=True` in `.env`. STK pushes are faked and "succeed" after about 15 seconds. This lets you test the whole POS and shop flow. **Never leave it on in production.**

### B. Sandbox (real Daraja API, fake money)
1. Create a free account at <https://developer.safaricom.co.ke>, add an app, and enable **M-Pesa Sandbox / Lipa na M-Pesa Online**.
2. Put the app's **Consumer Key / Secret** in `.env`. Keep the sandbox shortcode `174379` and the sandbox passkey from `.env.example` (check the Daraja docs if they have changed).
3. Safaricom must be able to reach your callback, so you need a public HTTPS address. In development use a tunnel such as `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`, then set:
   - `MPESA_CALLBACK_BASE_URL=https://<your-tunnel-host>`
   - `DJANGO_ALLOWED_HOSTS` to include that host, and `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-tunnel-host>`
   - `MPESA_CALLBACK_SECRET` to a long random string
4. Use the test phone number from the Daraja simulator when paying.

### C. Go live
1. On the Daraja portal use **Go Live** and link your **Paybill** or **Till**. You'll receive production credentials and a production **passkey** for your shortcode.
2. Update `.env`:
   - `MPESA_ENV=production`, new consumer key/secret, `MPESA_PASSKEY`
   - **Paybill:** `MPESA_SHORTCODE=<paybill>`, `MPESA_TRANSACTION_TYPE=CustomerPayBillOnline`, leave `MPESA_PARTY_B` empty
   - **Till (Buy Goods):** `MPESA_SHORTCODE=<store/head-office number>`, `MPESA_PARTY_B=<till number>`, `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline`
   - `MPESA_SIMULATE=False`
3. Serve the app over HTTPS on your own domain and set `MPESA_CALLBACK_BASE_URL` to it.
4. Make one real KES 1 payment and confirm it shows as Paid with an M-Pesa receipt number.

## Running in production (outline)
- `DJANGO_DEBUG=False`, a real `DJANGO_SECRET_KEY`, correct `DJANGO_ALLOWED_HOSTS`.
- `python manage.py collectstatic`, then `gunicorn config.wsgi` behind nginx/Caddy with HTTPS (static files are served by WhiteNoise).
- Add a cron job every 5 minutes: `python manage.py expire_pending_sales` (returns stock held by abandoned unpaid orders).
- Back up the PostgreSQL database daily.

## Compliance reminders (your responsibility)
- Selling alcohol to anyone under 18 is illegal in Kenya. The POS and shop both require an age confirmation; staff should still check ID when in doubt.
- Display your county liquor licence, and put the licence number in `STORE_LIQUOR_LICENCE` so it prints on receipts and the shop footer.
- If you're VAT-registered or need KRA eTIMS-compliant receipts, this app's receipts are **not** a substitute; integrating eTIMS is a separate piece of work.

## Project layout

```
config/      settings, URLs
accounts/    custom User with roles, role decorator, login
inventory/   products, categories, stock movements, low-stock alerts
sales/       POS screen + API, sales, receipts, sale lifecycle (sales/services.py)
payments/    Payment model, Daraja client (mpesa.py), callback + status endpoints
reports/     dashboard and CSV export
shop/        public storefront, cart, checkout, order tracking
templates/ static/
```

## Ideas for later
Delivery fees and riders, customer accounts and order history, discounts/promotions, supplier purchase orders, multiple branches, per-shift cash-up (opening/closing float), eTIMS integration, refunds via the Daraja reversal API.
