# Deploy Milho Verde

## Arquitetura recomendada

- Supabase: banco PostgreSQL principal.
- Railway: consulta web/mobile Flask.
- Executavel Windows: roda nos PCs e conecta no Supabase via `config.ini`.

## 1. Preparar Supabase

1. No Supabase, abra o projeto.
2. Va em Project Settings > Database.
3. Copie os dados da connection string:
   - host
   - port
   - database
   - user
   - password
   - sslmode=require

## 2. Criar `config.ini` local

Copie `config_exemplo.ini` para `config.ini` na raiz do projeto e preencha:

```ini
[postgres]
host=db.SEUPROJETO.supabase.co
port=5432
dbname=postgres
user=postgres
password=SUA_SENHA_DO_BANCO
sslmode=require
```

## 3. Migrar dados locais para Supabase

Feche o sistema em todos os PCs antes de migrar.

Depois rode:

```powershell
python .\migrar_para_supabase.py
```

O script vai pedir confirmacao digitando `MIGRAR`, porque ele limpa as tabelas do destino antes de copiar os dados locais.

## 4. Testar executavel com Supabase

Depois da migracao, rode o sistema com o `config.ini` ao lado do executavel.

Confira:

- vendas
- clientes
- produtores
- diarias
- folha/holerits
- usuarios

## 5. Deploy da consulta web no Railway

No Railway:

1. Crie um projeto apontando para o repositorio GitHub.
2. Configure as variaveis de ambiente:

```env
PGHOST=db.SEUPROJETO.supabase.co
PGPORT=5432
PGDATABASE=postgres
PGUSER=postgres
PGPASSWORD=SUA_SENHA_DO_BANCO
PGSSLMODE=require
CONSULTA_SECRET_KEY=uma-chave-grande-aleatoria
CONSULTA_ALLOW_DEV_LOGIN=0
```

3. O Railway deve usar o `Procfile`:

```text
web: gunicorn consulta_web.app:app --bind 0.0.0.0:$PORT
```

## 6. Login da consulta web

A consulta web usa a tabela `usuarios` do sistema principal.

O login piloto `consulta/consulta` fica desativado no deploy quando:

```env
CONSULTA_ALLOW_DEV_LOGIN=0
```

## Observacao

Nao envie `config.ini`, `.env`, backups ou senhas para o GitHub.
