Piloto de consulta web/mobile do Milho Verde

Como rodar:
  python consulta_web/app.py

Abrir no computador:
  http://localhost:5000

Abrir no celular:
  1. Deixe o computador e o celular na mesma rede Wi-Fi.
  2. Rode: python consulta_web/app.py
  3. Use no celular o endereco mostrado no terminal:
     http://IP_DO_COMPUTADOR:5000

Login piloto:
  usuario: consulta
  senha: consulta

Tambem entra com:
  usuario: admin
  senha: admin123

Observacao:
  Esta versao e somente consulta. Nao altera dados.
  Ela usa o mesmo config.ini da raiz do projeto quando existir.
  Sem config.ini, conecta no PostgreSQL local usando:
    host localhost
    porta 5432
    banco milhoverde
    usuario postgres
    senha MilhoVerde@2026

Supabase:
  Copie config_exemplo.ini para config.ini na raiz do projeto e preencha:
    host
    port
    dbname
    user
    password
    sslmode=require
