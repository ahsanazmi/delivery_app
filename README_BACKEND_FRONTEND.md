Quick guide: run backend and frontend locally

Backend (FastAPI)

- cd backend
- python3 -m venv .venv
- source .venv/bin/activate
- pip install -r requirements.txt
- uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Notes for Android emulator

- Use `http://10.0.2.2:8000` as backend base URL from Android emulator.
- For physical device, use host machine IP (e.g., `http://192.168.x.x:8000`).

Frontend (Expo)

- From project root (say_hi_chai), run:

```bash
npm install
npx expo start
```

- Expo app will load. Ensure `API_BASE_URL` env is set if needed.
