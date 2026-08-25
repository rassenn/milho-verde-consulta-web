import os
import socket
import configparser
import hashlib
import hmac
from functools import wraps

import psycopg
from flask import Flask, redirect, render_template, request, session, url_for


app = Flask(__name__)
app.secret_key = os.getenv("CONSULTA_SECRET_KEY", "milho-verde-consulta-dev")


def caminho_config():
    candidatos = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"),
    ]
    for caminho in candidatos:
        if os.path.exists(caminho):
            return caminho
    return candidatos[0]


def carregar_config_banco():
    config = configparser.ConfigParser()
    config_path = caminho_config()
    if os.path.exists(config_path):
        config.read(config_path, encoding="utf-8")

    secao = config["postgres"] if config.has_section("postgres") else {}

    def valor(chave_ini, env_nome, padrao):
        if config.has_section("postgres"):
            bruto = secao.get(chave_ini, fallback="")
        else:
            bruto = ""
        return os.getenv(env_nome, bruto or padrao)

    conninfo = {
        "host": valor("host", "PGHOST", "localhost"),
        "port": int(valor("port", "PGPORT", "5432")),
        "dbname": valor("dbname", "PGDATABASE", "milhoverde"),
        "user": valor("user", "PGUSER", "postgres"),
        "password": valor("password", "PGPASSWORD", "MilhoVerde@2026"),
    }
    sslmode = valor("sslmode", "PGSSLMODE", "")
    if sslmode:
        conninfo["sslmode"] = sslmode
    return conninfo


def pg_conninfo():
    return carregar_config_banco()


def query(sql, params=(), one=False):
    with psycopg.connect(**pg_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc.name for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            return rows[0] if one and rows else None if one else rows


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapper


def dinheiro(valor):
    valor = float(valor or 0)
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


app.jinja_env.filters["dinheiro"] = dinheiro


def verificar_senha(senha, senha_hash):
    try:
        salt_hex, digest_hex = str(senha_hash or "").split(":", 1)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", str(senha).encode("utf-8"), salt, 120000).hex()
        return hmac.compare_digest(digest, digest_hex)
    except Exception:
        return False


MES_DIARIA_EXPR = (
    "CASE WHEN substr(data,5,1) = '-' "
    "THEN substr(data,1,7) "
    "ELSE substr(data,7,4) || '-' || substr(data,4,2) END"
)

DATA_VENDA_EXPR = (
    "CASE WHEN substr(v.data,5,1) = '-' "
    "THEN v.data "
    "ELSE substr(v.data,7,4) || '-' || substr(v.data,4,2) || '-' || substr(v.data,1,2) END"
)


def mes_padrao_holerit():
    row = query(
        f"""
        SELECT COALESCE(MAX({MES_DIARIA_EXPR}), TO_CHAR(CURRENT_DATE, 'YYYY-MM')) AS mes
        FROM diarias_funcionarios
        """,
        one=True,
    )
    return row["mes"]


def normalizar_data_filtro(data):
    texto = (data or "").strip()
    if not texto:
        return ""
    partes = texto.split("/")
    if len(partes) == 3:
        dia, mes, ano = partes
        if dia.isdigit() and mes.isdigit() and ano.isdigit():
            return f"{ano.zfill(4)}-{mes.zfill(2)}-{dia.zfill(2)}"
    return texto


def ip_lan():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "localhost"


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "").strip()

        row = query(
            """
            SELECT nome, login, senha_hash, perfil
            FROM usuarios
            WHERE login = %s AND COALESCE(ativo, 1) = 1
            """,
            (usuario,),
            one=True,
        )
        if row and verificar_senha(senha, row["senha_hash"]):
            session["usuario"] = {
                "nome": row["nome"],
                "login": row["login"],
                "perfil": row["perfil"],
            }
            return redirect(url_for("index"))

        if os.getenv("CONSULTA_ALLOW_DEV_LOGIN", "0").strip().lower() in ("1", "true", "sim", "yes"):
            if usuario.lower() in ("admin", "consulta") and senha in ("admin123", "consulta"):
                session["usuario"] = {"nome": usuario, "login": usuario, "perfil": "CONSULTA"}
                return redirect(url_for("index"))

        erro = "Usuario ou senha invalidos."

    return render_template("login.html", erro=erro)


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    resumo = query(
        """
        SELECT
            COALESCE((SELECT SUM(valor_cliente) FROM vendas), 0) AS total_clientes,
            COALESCE((SELECT SUM(pag_produtor) FROM vendas), 0) AS total_produtores,
            COALESCE((SELECT SUM(valor_pendente) FROM vendas), 0) AS pendente_produtores,
            COALESCE((SELECT SUM(valor_pago) FROM pagamentos_produtor), 0) AS pago_produtores,
            COALESCE((SELECT COUNT(*) FROM vendas), 0) AS qtd_vendas,
            COALESCE((SELECT COUNT(*) FROM clientes), 0) AS qtd_clientes
        """,
        one=True,
    )
    recentes = query(
        """
        SELECT id, data, COALESCE(romaneio, '') AS romaneio, cliente, produtor,
               COALESCE(peso, 0) AS peso, COALESCE(valor_cliente, 0) AS valor_cliente
        FROM vendas
        ORDER BY substr(data,7,4) DESC, substr(data,4,2) DESC, substr(data,1,2) DESC, id DESC
        LIMIT 8
        """
    )
    mes_ref = mes_padrao_holerit()
    holerits = query(
        f"""
        WITH movimentos AS (
            SELECT funcionario_id, SUM(COALESCE(valor, 0)) AS valor_bruto
            FROM diarias_funcionarios
            WHERE {MES_DIARIA_EXPR} = %s
            GROUP BY funcionario_id
        )
        SELECT f.nome, COALESCE(m.valor_bruto, 0) AS valor_bruto,
               COALESCE(fp.vale, 0) AS vale, COALESCE(fp.inss, 0) AS inss,
               COALESCE(fp.valor_liquido, COALESCE(m.valor_bruto, 0) - COALESCE(fp.vale, 0) - COALESCE(fp.inss, 0)) AS valor_liquido
        FROM movimentos m
        JOIN funcionarios f ON f.id = m.funcionario_id
        LEFT JOIN folha_pagamento fp ON fp.funcionario_id = f.id AND fp.mes = %s
        ORDER BY f.nome
        LIMIT 6
        """,
        (mes_ref, mes_ref),
    )
    return render_template("index.html", resumo=resumo, recentes=recentes, holerits=holerits, mes_ref=mes_ref)


@app.route("/vendas")
@login_required
def vendas():
    termo = request.args.get("q", "").strip()
    params = []
    sql = """
        SELECT id, data, COALESCE(romaneio, '') AS romaneio, cliente, produtor,
               COALESCE(peso, 0) AS peso, COALESCE(valor_cliente, 0) AS valor_cliente,
               COALESCE(pag_produtor, 0) AS valor_produtor,
               COALESCE(situacao_cliente, '') AS situacao_cliente,
               COALESCE(situacao_produtor, '') AS situacao_produtor
        FROM vendas
        WHERE 1=1
    """
    if termo:
        sql += " AND (cliente ILIKE %s OR produtor ILIKE %s OR COALESCE(romaneio, '') ILIKE %s)"
        busca = f"%{termo}%"
        params.extend([busca, busca, busca])
    sql += " ORDER BY substr(data,7,4) DESC, substr(data,4,2) DESC, substr(data,1,2) DESC, id DESC LIMIT 80"
    rows = query(sql, params)
    return render_template("vendas.html", rows=rows, termo=termo)


@app.route("/clientes")
@login_required
def clientes():
    termo = request.args.get("q", "").strip()
    params = []
    sql = """
        SELECT nome, cidade, telefone, COALESCE(saldo, 0) AS saldo,
               COALESCE(credito, 0) AS credito, COALESCE(situacao, '') AS situacao
        FROM clientes
        WHERE 1=1
    """
    if termo:
        sql += " AND nome ILIKE %s"
        busca = f"%{termo}%"
        params.append(busca)
    sql += " ORDER BY nome LIMIT 120"
    rows = query(sql, params)

    movimentos = []
    totais = {"peso": 0, "valor": 0, "qtd": 0}
    if termo:
        movimentos = query(
            f"""
            SELECT v.data, v.produtor, COALESCE(v.peso, 0) AS peso,
                   COALESCE(v.valor_cliente, 0) AS valor,
                   COALESCE(v.situacao_cliente, '') AS situacao
            FROM vendas v
            WHERE v.cliente ILIKE %s
            ORDER BY {DATA_VENDA_EXPR} DESC, v.id DESC
            LIMIT 20
            """,
            (f"%{termo}%",),
        )
        total_row = query(
            """
            SELECT COALESCE(SUM(peso), 0) AS peso,
                   COALESCE(SUM(valor_cliente), 0) AS valor,
                   COUNT(*) AS qtd
            FROM vendas
            WHERE cliente ILIKE %s
            """,
            (f"%{termo}%",),
            one=True,
        )
        totais = {
            "peso": float(total_row["peso"] or 0),
            "valor": float(total_row["valor"] or 0),
            "qtd": int(total_row["qtd"] or 0),
        }

    return render_template(
        "pessoas.html",
        titulo="Clientes",
        rota="clientes",
        rows=rows,
        termo=termo,
        movimentos=movimentos,
        totais=totais,
    )


@app.route("/produtores")
@login_required
def produtores():
    termo = request.args.get("q", "").strip()
    fazenda = request.args.get("fazenda", "").strip()
    data = request.args.get("data", "").strip()
    data_sql = normalizar_data_filtro(data)
    params = []
    sql = """
        SELECT nome, cidade, telefone, COALESCE(saldo, 0) AS saldo,
               COALESCE(credito, 0) AS credito, COALESCE(situacao, '') AS situacao
        FROM produtores
        WHERE 1=1
    """
    if termo:
        sql += " AND nome ILIKE %s"
        busca = f"%{termo}%"
        params.append(busca)
    sql += " ORDER BY nome LIMIT 120"
    rows = query(sql, params)

    movimentos = []
    fazendas = []
    totais = {"peso": 0, "valor": 0, "pago": 0, "pendente": 0, "qtd": 0}
    if termo:
        fazendas = query(
            """
            SELECT DISTINCT COALESCE(fp.nome_fazenda, '') AS nome
            FROM vendas v
            LEFT JOIN fazendas_produtor fp ON fp.id = v.fazenda_id
            WHERE v.produtor ILIKE %s
              AND COALESCE(fp.nome_fazenda, '') <> ''
            ORDER BY nome
            """,
            (f"%{termo}%",),
        )
        filtros = ["v.produtor ILIKE %s"]
        mov_params = [f"%{termo}%"]
        if fazenda:
            filtros.append("COALESCE(fp.nome_fazenda, '') = %s")
            mov_params.append(fazenda)
        if data_sql:
            filtros.append(f"{DATA_VENDA_EXPR} = %s")
            mov_params.append(data_sql)
        where_mov = " AND ".join(filtros)
        movimentos = query(
            f"""
            SELECT v.data, v.cliente, COALESCE(fp.nome_fazenda, '') AS fazenda,
                   COALESCE(v.peso, 0) AS peso,
                   COALESCE(v.pag_produtor, 0) AS valor,
                   COALESCE(v.situacao_produtor, '') AS situacao
            FROM vendas v
            LEFT JOIN fazendas_produtor fp ON fp.id = v.fazenda_id
            WHERE {where_mov}
            ORDER BY {DATA_VENDA_EXPR} DESC, v.id DESC
            LIMIT 20
            """,
            mov_params,
        )
        total_row = query(
            f"""
            SELECT COALESCE(SUM(v.peso), 0) AS peso,
                   COALESCE(SUM(v.pag_produtor), 0) AS valor,
                   COALESCE(SUM(CASE WHEN UPPER(COALESCE(v.situacao_produtor, '')) = 'PAGO'
                                     THEN v.pag_produtor ELSE 0 END), 0) AS pago,
                   COALESCE(SUM(CASE WHEN UPPER(COALESCE(v.situacao_produtor, '')) = 'PAGO'
                                     THEN 0 ELSE v.pag_produtor END), 0) AS pendente,
                   COUNT(*) AS qtd
            FROM vendas v
            LEFT JOIN fazendas_produtor fp ON fp.id = v.fazenda_id
            WHERE {where_mov}
            """,
            mov_params,
            one=True,
        )
        totais = {
            "peso": float(total_row["peso"] or 0),
            "valor": float(total_row["valor"] or 0),
            "pago": float(total_row["pago"] or 0),
            "pendente": float(total_row["pendente"] or 0),
            "qtd": int(total_row["qtd"] or 0),
        }

    return render_template(
        "pessoas.html",
        titulo="Produtores",
        rota="produtores",
        rows=rows,
        termo=termo,
        fazenda=fazenda,
        fazendas=fazendas,
        data=data,
        movimentos=movimentos,
        totais=totais,
    )


@app.route("/holerits")
@login_required
def holerits():
    mes_padrao = mes_padrao_holerit()
    mes = request.args.get("mes", mes_padrao).strip() or mes_padrao
    termo = request.args.get("q", "").strip()
    params = [mes, mes]
    sql = f"""
        WITH movimentos AS (
            SELECT funcionario_id, SUM(COALESCE(valor, 0)) AS valor_bruto
            FROM diarias_funcionarios
            WHERE {MES_DIARIA_EXPR} = %s
            GROUP BY funcionario_id
        )
        SELECT f.id, f.nome, COALESCE(f.cargo, '') AS cargo,
               COALESCE(fp.vale, 0) AS vale,
               COALESCE(fp.inss, 0) AS inss,
               COALESCE(m.valor_bruto, 0) AS valor_bruto,
               COALESCE(fp.valor_liquido, COALESCE(m.valor_bruto, 0) - COALESCE(fp.vale, 0) - COALESCE(fp.inss, 0)) AS valor_liquido
        FROM movimentos m
        JOIN funcionarios f ON f.id = m.funcionario_id
        LEFT JOIN folha_pagamento fp ON fp.funcionario_id = f.id AND fp.mes = %s
        WHERE 1=1
    """
    if termo:
        sql += " AND f.nome ILIKE %s"
        params.append(f"%{termo}%")
    sql += " ORDER BY f.nome"
    rows = query(sql, params)
    totais = {
        "bruto": sum(float(r["valor_bruto"] or 0) for r in rows),
        "vale": sum(float(r["vale"] or 0) for r in rows),
        "inss": sum(float(r["inss"] or 0) for r in rows),
        "liquido": sum(float(r["valor_liquido"] or 0) for r in rows),
    }
    return render_template("holerits.html", rows=rows, mes=mes, termo=termo, totais=totais)


@app.route("/agenda")
@login_required
def agenda():
    termo = request.args.get("q", "").strip()
    params = []
    sql = """
        SELECT data, hora, tipo, categoria, pessoa_nome, descricao, COALESCE(valor, 0) AS valor,
               COALESCE(usuario_nome, '') AS usuario_nome
        FROM historico_diario
        WHERE 1=1
    """
    if termo:
        sql += " AND (descricao ILIKE %s OR pessoa_nome ILIKE %s OR tipo ILIKE %s)"
        busca = f"%{termo}%"
        params.extend([busca, busca, busca])
    sql += " ORDER BY criado_em DESC, id DESC LIMIT 100"
    rows = query(sql, params)
    return render_template("agenda.html", rows=rows, termo=termo)


if __name__ == "__main__":
    host = os.getenv("CONSULTA_HOST", "0.0.0.0")
    port = int(os.getenv("CONSULTA_PORT", "5000"))
    debug = os.getenv("CONSULTA_DEBUG", "0").strip().lower() in ("1", "true", "sim", "yes")
    endereco_celular = f"http://{ip_lan()}:{port}"
    print("\nConsulta Web Milho Verde")
    print(f"Computador: http://localhost:{port}")
    print(f"Celular na mesma rede Wi-Fi: {endereco_celular}\n")
    app.run(host=host, port=port, debug=debug, use_reloader=False)
