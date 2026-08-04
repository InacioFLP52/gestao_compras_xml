import streamlit as st
import pandas as pd
import sqlite3
import xml.etree.ElementTree as ET
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAÇÃO E BANCO DE DADOS (SQLite)
# ==============================================================================
def init_db():
    conn = sqlite3.connect('compras_inteligentes.db')
    cursor = conn.cursor()
    
    # Tabela 1: Cadastro único de fornecedores (por CNPJ)
    cursor.execute('''CREATE TABLE IF NOT EXISTS fornecedores (
                        cnpj TEXT PRIMARY KEY, 
                        nome TEXT)''')
    
    # Tabela 2: Seu catálogo mestre de produtos
    cursor.execute('''CREATE TABLE IF NOT EXISTS produtos_internos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        nome_interno TEXT)''')
    
    # Tabela 3: A inteligência do "De/Para" com fator de conversão
    cursor.execute('''CREATE TABLE IF NOT EXISTS de_para (
                        id_vinculo INTEGER PRIMARY KEY AUTOINCREMENT,
                        cnpj_fornecedor TEXT,
                        cod_xml TEXT,
                        id_interno INTEGER,
                        fator_conversao REAL DEFAULT 1,
                        FOREIGN KEY(cnpj_fornecedor) REFERENCES fornecedores(cnpj),
                        FOREIGN KEY(id_interno) REFERENCES produtos_internos(id))''')
    
    # Tabela 4: Histórico de transações e valores por compra
    cursor.execute('''CREATE TABLE IF NOT EXISTS historico (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        id_interno INTEGER,
                        data TEXT,
                        qtd REAL,
                        valor_unit REAL,
                        chave TEXT)''')
    
    conn.commit()
    return conn

# ==============================================================================
# 2. FUNÇÃO DE EXTRAÇÃO DE DADOS DO XML (NF-e)
# ==============================================================================
def extrair_xml(arquivo):
    ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
    tree = ET.parse(arquivo)
    root = tree.getroot()
    
    # Cabeçalho da Nota
    inf = root.find(".//nfe:infNFe", ns)
    chave = inf.attrib['Id'][3:] # Remove o prefixo 'NFe'
    data = root.find(".//nfe:ide/nfe:dhEmi", ns).text[:10]
    cnpj_f = root.find(".//nfe:emit/nfe:CNPJ", ns).text
    nome_f = root.find(".//nfe:emit/nfe:xNome", ns).text

    # Varredura dos itens
    itens = []
    for det in root.findall(".//nfe:det", ns):
        prod = det.find("nfe:prod", ns)
        itens.append({
            "cod_xml": prod.find("nfe:cProd", ns).text,
            "nome_xml": prod.find("nfe:xProd", ns).text,
            "qtd": float(prod.find("nfe:qCom", ns).text),
            "v_unit": float(prod.find("nfe:vUnCom", ns).text)
        })
    return cnpj_f, nome_f, data, chave, itens

# ==============================================================================
# 3. INTERFACE VISUAL (Streamlit) & LÓGICA DE PROCESSAMENTO
# ==============================================================================
st.set_page_config(page_title="Gestão XML Pro", layout="wide")
st.title("📦 Sistema Inteligente de Gestão de Compras")

# Inicializa conexão com o banco
conn = init_db()

# Painel Lateral para envio da NF-e
st.sidebar.header("Importar Nota")
file = st.sidebar.file_uploader("Arraste o XML da NF-e aqui", type="xml")

if file:
    cnpj_f, nome_f, data, chave, itens = extrair_xml(file)
    
    st.subheader(f"📄 NF-e: {chave}")
    st.info(f"Fornecedor: {nome_f} ({cnpj_f}) | Data: {data}")

    # Processamento item por item da nota
    for item in itens:
        with st.expander(f"Item: {item['nome_xml']} (Cód: {item['cod_xml']})"):
            c1, c2, c3 = st.columns([2, 1, 1])
            
            # Consulta se o produto já possui vínculo "De/Para" cadastrado
            cursor = conn.cursor()
            cursor.execute("SELECT id_interno, fator_conversao FROM de_para WHERE cnpj_fornecedor=? AND cod_xml=?", (cnpj_f, item['cod_xml']))
            vinculo = cursor.fetchone()

            if vinculo:
                id_int, fator = vinculo
                cursor.execute("SELECT nome_interno FROM produtos_internos WHERE id=?", (id_int,))
                nome_int = cursor.fetchone()[0]
                c1.success(f"Vinculado a: **{nome_int}**")
                c2.write(f"Fator: {fator}")
                
                if c3.button("Confirmar Entrada", key=f"btn_{item['cod_xml']}"):
                    qtd_final = item['qtd'] * fator
                    val_final = item['v_unit'] / fator
                    cursor.execute("INSERT INTO historico (id_interno, data, qtd, valor_unit, chave) VALUES (?,?,?,?,?)",
                                   (id_int, data, qtd_final, val_final, chave))
                    conn.commit()
                    st.toast("Item registrado com sucesso!")
            else:
                c1.warning("Produto não mapeado!")
                cursor.execute("SELECT id, nome_interno FROM produtos_internos")
                prods_existentes = cursor.fetchall()
                opcoes = {p[1]: p[0] for p in prods_existentes}
                
                escolha = c1.selectbox("Vincular a produto existente:", ["-- Novo Cadastro --"] + list(opcoes.keys()), key=f"sel_{item['cod_xml']}")
                fator_novo = c2.number_input("Fator de Conversão:", value=1.0, key=f"fat_{item['cod_xml']}")
                
                if c3.button("Gravar Vínculo", key=f"save_{item['cod_xml']}"):
                    cursor.execute("INSERT OR IGNORE INTO fornecedores VALUES (?,?)", (cnpj_f, nome_f))
                    
                    if escolha == "-- Novo Cadastro --":
                        cursor.execute("INSERT INTO produtos_internos (nome_interno) VALUES (?)", (item['nome_xml'],))
                        id_int = cursor.lastrowid
                    else:
                        id_int = opcoes[escolha]
                    
                    cursor.execute("INSERT INTO de_para (cnpj_fornecedor, cod_xml, id_interno, fator_conversao) VALUES (?,?,?,?)",
                                   (cnpj_f, item['cod_xml'], id_int, fator_novo))
                    conn.commit()
                    st.rerun()

st.divider()

# ==============================================================================
# 4. GRÁFICOS E HISTÓRICO DE PREÇOS
# ==============================================================================
st.header("📊 Análise de Preços Históricos")
df_hist = pd.read_sql_query("""
    SELECT h.data, p.nome_interno, h.valor_unit, f.nome as fornecedor
    FROM historico h
    JOIN produtos_internos p ON h.id_interno = p.id
    JOIN de_para dp ON p.id = dp.id_interno
    JOIN fornecedores f ON dp.cnpj_fornecedor = f.cnpj
""", conn)

if not df_hist.empty:
    prod_alvo = st.selectbox("Selecione o produto para análise:", df_hist['nome_interno'].unique())
    df_filtrado = df_hist[df_hist['nome_interno'] == prod_alvo].sort_values('data')
    
    fig = px.line(df_filtrado, x='data', y='valor_unit', color='fornecedor', markers=True,
                  title=f"Evolução de Preço Unitário: {prod_alvo}")
    st.plotly_chart(fig, use_container_width=True)
    
    st.subheader("Últimas Entradas")
    st.dataframe(df_filtrado, use_container_width=True)
else:
    st.write("Nenhuma compra registrada ainda. Importe um XML na barra lateral para começar.")