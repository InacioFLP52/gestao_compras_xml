import sqlite3
import xml.etree.ElementTree as ET
import pandas as pd
import plotly.express as px
import streamlit as st

# Configuração da página
st.set_page_config(page_title="Gestão de Compras NF-e", layout="wide")

# Conexão com o banco de dados SQLite
DB_NAME = "compras_inteligentes.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor TEXT,
            data TEXT,
            produto TEXT,
            quantidade REAL,
            valor_unit REAL,
            valor_total REAL
        )
    """)
    conn.commit()
    conn.close()


# Inicializa o banco de dados se não existir
init_db()


def processar_xml(xml_file):
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Namespace do XML da NF-e
        ns = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

        # Identificação do fornecedor e data
        emitente = root.find(".//nfe:emit/nfe:xNome", ns)
        fornecedor = emitente.text if emitente is not None else "Desconhecido"

        dhEmi = root.find(".//nfe:ide/nfe:dhEmi", ns)
        if dhEmi is not None:
            data = dhEmi.text[:10]
        else:
            dEmi = root.find(".//nfe:ide/dEmi", ns)
            data = dEmi.text[:10] if dEmi is not None else "2026-01-01"

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Leitura dos itens da nota
        for det in root.findall(".//nfe:det", ns):
            prod = det.find("nfe:prod", ns)
            produto = prod.find("nfe:xProd", ns).text
            qCom = float(prod.find("nfe:qCom", ns).text)
            vUnCom = float(prod.find("nfe:vUnCom", ns).text)
            vProd = float(prod.find("nfe:vProd", ns).text)

            cursor.execute(
                """
                INSERT INTO compras (fornecedor, data, produto, quantidade, valor_unit, valor_total)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (fornecedor, data, produto, qCom, vUnCom, vProd),
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro ao processar o arquivo XML: {e}")
        return False


# --- BARRA LATERAL (SIDEBAR) ---
st.sidebar.title("Importar Nota")
uploaded_file = st.sidebar.file_uploader(
    "Arraste o XML da NF-e aqui", type=["xml"]
)

if uploaded_file is not None:
    if processar_xml(uploaded_file):
        st.sidebar.success("Nota importada com sucesso!")
        st.rerun()

# --- NOVO BOTÃO: ZERAR BANCO DE DADOS ---
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Configurações")

if st.sidebar.button("🗑️ Zerar Banco de Dados", type="primary"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM compras")
    conn.commit()
    conn.close()
    st.sidebar.success("Banco de dados limpo com sucesso!")
    st.rerun()


# --- CORPO PRINCIPAL DO APP ---
st.title("📦 Sistema Inteligente de Gestão de Compras")

# Carregar dados do banco
conn = sqlite3.connect(DB_NAME)
df = pd.read_sql_query("SELECT * FROM compras", conn)
conn.close()

if not df.empty:
    st.header("📊 Análise de Preços Históricos")

    produtos = df["produto"].unique()
    produto_selecionado = st.selectbox(
        "Selecione o produto para análise:", produtos
    )

    df_prod = df[df["produto"] == produto_selecionado].sort_values("data")

    fig = px.line(
        df_prod,
        x="data",
        y="valor_unit",
        color="fornecedor",
        markers=True,
        title=f"Evolução de Preço Unitário: {produto_selecionado}",
        labels={
            "data": "Data",
            "valor_unit": "Valor Unitário (R$)",
            "fornecedor": "Fornecedor",
        },
    )
    st.plotly_chart(fig, use_container_width=True)

    st.header("Últimas Entradas")
    st.dataframe(df, use_container_width=True)
else:
    st.info(
        "Nenhuma nota fiscal cadastrada ainda. Use a barra lateral para importar o primeiro arquivo XML!"
    )
