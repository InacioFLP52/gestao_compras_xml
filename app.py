import streamlit as st
import pandas as pd
import sqlite3
import xml.etree.ElementTree as ET
import plotly.express as px

# ==========================================
# 1. CONFIGURAÇÃO E BANCO DE DADOS (SQLite)
# ==========================================

DB_FILE = 'compras_inteligentes.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Fornecedores
    cursor.execute('''CREATE TABLE IF NOT EXISTS fornecedores (
                        cnpj TEXT PRIMARY KEY,
                        nome TEXT)''')
    
    # Catálogo de Produtos
    cursor.execute('''CREATE TABLE IF NOT EXISTS produtos_catalogo (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome_padronizado TEXT UNIQUE)''')
    
    # De-Para
    cursor.execute('''CREATE TABLE IF NOT EXISTS de_para (
                        cnpj_fornecedor TEXT,
                        nome_produto_fornecedor TEXT,
                        id_produto_catalogo INTEGER,
                        PRIMARY KEY (cnpj_fornecedor, nome_produto_fornecedor),
                        FOREIGN KEY (cnpj_fornecedor) REFERENCES fornecedores(cnpj),
                        FOREIGN KEY (id_produto_catalogo) REFERENCES produtos_catalogo(id))''')
    
    # Histórico de Compras (Com REGRA ÚNICA para evitar duplicatas ao navegar)
    cursor.execute('''CREATE TABLE IF NOT EXISTS compras (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        numero_nfe TEXT,
                        data_emissao DATE,
                        cnpj_fornecedor TEXT,
                        nome_produto_fornecedor TEXT,
                        id_produto_catalogo INTEGER,
                        quantidade REAL,
                        valor_unitario REAL,
                        valor_total REAL,
                        UNIQUE(numero_nfe, cnpj_fornecedor, nome_produto_fornecedor, quantidade, valor_total),
                        FOREIGN KEY (cnpj_fornecedor) REFERENCES fornecedores(cnpj),
                        FOREIGN KEY (id_produto_catalogo) REFERENCES produtos_catalogo(id))''')
    
    conn.commit()
    conn.close()

init_db()

# Função auxiliar para extrair texto de tag com segurança
def get_xml_text(element, path, ns, default=""):
    if element is None:
        return default
    node = element.find(path, ns) if ns else element.find(path)
    if node is not None and node.text is not None:
        return node.text.strip()
    return default

# Função para processar e salvar a NF-e no SQLite
def processar_nfe(xml_file):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    ns = {'nfe': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
    prefix = 'nfe:' if ns else ''
    
    infNfe = root.find(f'.//{prefix}infNFe', ns) if ns else root.find('.//infNFe')
    if infNfe is None:
        infNfe = root

    ide = infNfe.find(f'{prefix}ide', ns) if ns else infNfe.find('ide')
    emit = infNfe.find(f'{prefix}emit', ns) if ns else infNfe.find('emit')
    
    nNF = get_xml_text(ide, f'{prefix}nNF', ns, "000")
    dhEmi = get_xml_text(ide, f'{prefix}dhEmi', ns, get_xml_text(ide, f'{prefix}dEmi', ns, "2026-01-01"))[:10]
    
    cnpj_emit = get_xml_text(emit, f'{prefix}CNPJ', ns, "00000000000000")
    xNome_emit = get_xml_text(emit, f'{prefix}xNome', ns, "Fornecedor Desconhecido")
    
    cursor.execute("INSERT OR IGNORE INTO fornecedores (cnpj, nome) VALUES (?, ?)", (cnpj_emit, xNome_emit))
    
    det_list = infNfe.findall(f'{prefix}det', ns) if ns else infNfe.findall('det')
    
    for det in det_list:
        prod = det.find(f'{prefix}prod', ns) if ns else det.find('prod')
        if prod is None:
            continue
            
        xProd = get_xml_text(prod, f'{prefix}xProd', ns, "Produto sem nome")
        
        try: qCom = float(get_xml_text(prod, f'{prefix}qCom', ns, "1"))
        except ValueError: qCom = 1.0
            
        try: vUnCom = float(get_xml_text(prod, f'{prefix}vUnCom', ns, "0"))
        except ValueError: vUnCom = 0.0
            
        try: vProd = float(get_xml_text(prod, f'{prefix}vProd', ns, "0"))
        except ValueError: vProd = 0.0
        
        cursor.execute("INSERT OR IGNORE INTO produtos_catalogo (nome_padronizado) VALUES (?)", (xProd,))
        cursor.execute("SELECT id FROM produtos_catalogo WHERE nome_padronizado = ?", (xProd,))
        res = cursor.fetchone()
        id_catalogo = res[0] if res else 1
        
        cursor.execute("INSERT OR IGNORE INTO de_para (cnpj_fornecedor, nome_produto_fornecedor, id_produto_catalogo) VALUES (?, ?, ?)",
                       (cnpj_emit, xProd, id_catalogo))
        
        # O 'INSERT OR IGNORE' impede a duplicação de itens da mesma nota fiscal
        cursor.execute('''INSERT OR IGNORE INTO compras 
                          (numero_nfe, data_emissao, cnpj_fornecedor, nome_produto_fornecedor, id_produto_catalogo, quantidade, valor_unitario, valor_total)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                       (nNF, dhEmi, cnpj_emit, xProd, id_catalogo, qCom, vUnCom, vProd))
        
    conn.commit()
    conn.close()

# ==========================================
# 2. INTERFACE GRÁFICA (Streamlit)
# ==========================================

st.set_page_config(page_title="Gestão de Compras NF-e", layout="wide")

# Barra Lateral - Upload
st.sidebar.title("Importar Nota")
uploaded_file = st.sidebar.file_uploader("Arraste o XML da NF-e aqui", type=["xml"])

if uploaded_file is not None:
    try:
        processar_nfe(uploaded_file)
        st.sidebar.success("NF-e processada com sucesso!")
    except Exception as e:
        st.sidebar.error(f"Erro ao processar o arquivo XML: {e}")

# Barra Lateral - Configurações
st.sidebar.markdown("---")
st.sidebar.title("⚙️ Configurações")

if st.sidebar.button("🗑️ Zerar Banco de Dados", type="primary"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS compras")
    cursor.execute("DROP TABLE IF EXISTS de_para")
    cursor.execute("DROP TABLE IF EXISTS fornecedores")
    cursor.execute("DROP TABLE IF EXISTS produtos_catalogo")
    conn.commit()
    conn.close()
    
    init_db()
    st.sidebar.warning("Banco de dados resetado com sucesso!")
    st.rerun()

# Conteúdo Principal
st.title("📦 Sistema de Gestão de Compras")

conn = sqlite3.connect(DB_FILE)
try:
    df_compras = pd.read_sql_query('''
        SELECT c.id, c.numero_nfe, c.data_emissao, f.nome as fornecedor, 
               p.nome_padronizado as produto, c.quantidade, c.valor_unitario, c.valor_total
        FROM compras c
        JOIN fornecedores f ON c.cnpj_fornecedor = f.cnpj
        JOIN produtos_catalogo p ON c.id_produto_catalogo = p.id
        ORDER BY c.data_emissao DESC
    ''', conn)
except Exception:
    df_compras = pd.DataFrame()
finally:
    conn.close()

if not df_compras.empty:
    st.subheader("📊 Análise de Histórico de Preços")
    
    produtos = df_compras['produto'].unique()
    produto_sel = st.selectbox("Selecione um produto para analisar:", produtos)
    
    df_prod = df_compras[df_compras['produto'] == produto_sel].sort_values('data_emissao')
    
    fig = px.line(df_prod, x='data_emissao', y='valor_unitario', color='fornecedor',
                  markers=True, title=f"Variação de Preço: {produto_sel}",
                  labels={'data_emissao': 'Data de Emissão', 'valor_unitario': 'R$ Valor Unitário'})
    st.plotly_chart(fig, use_container_width=True)
    
    st.subheader("📋 Todas as Compras Registradas")
    st.dataframe(df_compras, use_container_width=True)
else:
    st.info("Nenhuma nota fiscal cadastrada ainda. Use a barra lateral para importar o primeiro arquivo XML!")
