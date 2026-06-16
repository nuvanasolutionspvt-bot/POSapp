# POS App Backend

Django REST API for the POS frontend.

## Setup

1. Create a MySQL database:

```sql
CREATE DATABASE posapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. Create `backend/.env` from `.env.example` and set your local values:

```powershell
Copy-Item .env.example .env
```

Required database values:

```env
MYSQL_DATABASE=posapp
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
```

For Razorpay subscription payments, add your Razorpay Dashboard keys:

```env
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_razorpay_key_secret
RAZORPAY_CURRENCY=INR
```

Use test keys while testing. Replace them with live keys only when the app is ready for production payments.

For Firebase phone OTP login, download a Firebase Admin service account JSON from
Firebase Console > Project settings > Service accounts and place it in
`backend/firebase-service-account.json`. Then set:

```env
FIREBASE_SERVICE_ACCOUNT_PATH=firebase-service-account.json
FIREBASE_PROJECT_ID=nuva-bill
FIREBASE_CLIENT_PROJECT_ID=nuva-bill
```

Both project IDs must match `project_info.project_id` in the mobile app's
`android/app/google-services.json`. Download the service account from that same
Firebase project. The service account JSON is ignored by git. Do not commit it.

3. Run migrations:

```powershell
venv\Scripts\python.exe manage.py migrate
```

4. Start the API:

```powershell
venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

## API Roots

- Health: `GET /api/health/`
- Auth register: `POST /api/auth/register/`
- Auth login: `POST /api/auth/login/`
- Request OTP: `POST /api/auth/request-otp/`
- Verify OTP: `POST /api/auth/verify-otp/`
- Firebase login: `POST /api/auth/firebase-login/`
- Categories: `/api/categories/`
- Products: `/api/products/`
- Customers: `/api/customers/`
- Bills: `/api/bills/`
- Dashboard summary: `GET /api/dashboard/summary/`
- Reports summary: `GET /api/reports/summary/`
- Subscription current: `GET/POST /api/subscription/current/`
- Razorpay order: `POST /api/subscription/razorpay/create-order/`
- Razorpay verify: `POST /api/subscription/razorpay/verify/`
- Swagger docs: `/swagger/`

For local OTP testing, call `POST /api/auth/request-otp/?debug=true` to include
the generated OTP in the response. In production this should be replaced with an
SMS provider and `debug=true` should not be used.
