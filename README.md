# fihy

Report, Confirm & Get it Fixed. FIHY gives you a platform to share you local issues with your respective authorities. It also lets you build community to work on an issue independently.

## Layout

```
mobile/    React Native (Expo) app
backend/   FastAPI service
```

Each side is developed independently against the API contract in
`docs/api-contract.md`.

## Running the app

```bash
cd mobile
npm run demo     # in-memory data, no backend, no SMS, no camera
npm start        # against EXPO_PUBLIC_API_URL
```

Press `i` for the iOS simulator, or scan the QR code with Expo Go to run on a
physical device — Expo Go ships from the App Store, so it needs no local Xcode
toolchain and works on current iOS.

## Running the backend

```bash
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

It runs on SQLite with photos on disk until R2 and an SMS provider are
configured, so it needs no accounts to try. `backend/README.md` covers the
settings and answers the contract's open questions.
