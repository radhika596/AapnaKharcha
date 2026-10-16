# FinanceFlow
Personal finance platform: Flask, MySQL (SQLAlchemy), Chart.js.

## Run
```bash
pip install -r requirements.txt
mysql -u root -p -e "CREATE DATABASE financeflow CHARACTER SET utf8mb4"
export DATABASE_URL="mysql+pymysql://root:PASSWORD@localhost/financeflow"
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
flask --app app init-db
flask --app app run
```
## Test
`pytest -q` (uses in-memory SQLite, no MySQL needed)

## CSV import format
`date,description,amount[,type][,category]`. Without `type`, negative amounts are expenses. Blank categories are auto-assigned from keywords.
