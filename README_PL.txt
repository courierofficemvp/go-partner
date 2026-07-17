GO PARTNER Manager 5.0 POSTGRESQL / NEON

Ta wersja używa PostgreSQL w Neon przez zmienną DATABASE_URL.
Nie używa pliku go_partner.db.

RENDER
1. Environment musi zawierać DATABASE_URL i SECRET_KEY.
2. Build Command: pip install -r requirements.txt
3. Start Command: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120

TEST TRWAŁOŚCI
1. Po wdrożeniu otwórz /system/database.
2. Dodaj jednego testowego kierowcę.
3. W Render wykonaj Manual Deploy -> Deploy latest commit.
4. Sprawdź, czy kierowca nadal istnieje.

UWAGA O PLIKACH
Załączniki potwierdzeń zwrotu kaucji nadal są zapisywane lokalnie w uploads/.
Na darmowym Render mogą zniknąć po restarcie. Dane finansowe i rekordy w Neon pozostają.
