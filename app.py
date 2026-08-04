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
    
    # Histórico de Compras
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
    dhEmi = get_xml_text(ide, f'{prefix}dhEmi', ns, get_xml_text(ide, f'{prefix}dEmi', ns, "2026-08-01"))[:10]
    
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
            
        try:
            vProd_str = get_xml_text(prod, f'{prefix}vProd', ns, "0")
            vProd = float(vProd_str)
            if vProd == 0 and (qCom * vUnCom) > 0:
                vProd = round(qCom * vUnCom, 2)
        except ValueError:
            vProd = round(qCom * vUnCom, 2)
        
        cursor.execute("INSERT OR IGNORE INTO produtos_catalogo (nome_padronizado) VALUES (?)", (xProd,))
        cursor.execute("SELECT id FROM produtos_catalogo WHERE nome_padronizado = ?", (xProd,))
        res = cursor.fetchone()
        id_catalogo = res[0] if res else 1
        
        cursor.execute("INSERT OR IGNORE INTO de_para (cnpj_fornecedor, nome_produto_fornecedor, id_produto_catalogo) VALUES (?, ?, ?)",
                       (cnpj_emit, xProd, id_catalogo))
        
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
    
    # Converte coluna de data para o formato datetime
    df_compras['data_emissao_dt'] = pd.to_datetime(df_compras['data_emissao'])
    
    # --- PAINEL DE BUSCA E FILTROS ---
    st.markdown("### 🔍 Busca e Filtros Avançados")
    
    f_col1, f_col2, f_col3 = st.columns(3)
    
    with f_col1:
        # Filtro por Fornecedor (Empresa)
        lista_fornecedores = ["Todos"] + list(df_compras['fornecedor'].unique())
        fornecedor_sel = st.selectbox("Empresa / Fornecedor:", lista_fornecedores)
        
    with f_col2:
        # Filtro por Busca do Nome do Produto
        busca_produto = st.text_input("Buscar Produto (digite o nome):", "")
        
    with f_col3:
        # Filtro por Intervalo de Datas
        min_date = df_compras['data_emissao_dt'].min().date()
        max_date = df_compras['data_emissao_dt'].max().date()
        datas_sel = st.date_input("Período da Compra:", value=(min_date, max_date))

    # --- APLICAÇÃO DOS FILTROS ---
    df_filtrado = df_compras.copy()

    # 1. Aplica filtro de Empresa
    if fornecedor_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado['fornecedor'] == fornecedor_sel]

    # 2. Aplica filtro de Produto
    if busca_produto.strip() != "":
        df_filtrado = df_filtrado[df_filtrado['produto'].str.contains(busca_produto, case=False, na=False)]

    # 3. Aplica filtro de Data (garante intervalo completo)
    if isinstance(datas_sel, tuple) and len(datas_sel) == 2:
        dt_inicio, dt_fim = datas_sel
        df_filtrado = df_filtrado[(df_filtrado['data_emissao_dt'].dt.date >= dt_inicio) & 
                                  (df_filtrado['data_emissao_dt'].dt.date <= dt_fim)]

    st.markdown("---")

    if not df_filtrado.empty:
        # --- PAINEL DE GRÁFICOS ---
        st.subheader("📊 Análise de Compras (Filtrado)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            produtos_disponiveis = df_filtrado['produto'].unique()
            prod_grafico = st.selectbox("Selecione o produto para a linha de tempo:", produtos_disponiveis)
            df_prod = df_filtrado[df_filtrado['produto'] == prod_grafico].sort_values('data_emissao')
            
            fig_linha = px.line(df_prod, x='data_emissao', y='valor_unitario', color='fornecedor',
                                markers=True, title=f"Variação de Preço: {prod_grafico}",
                                labels={'data_emissao': 'Data', 'valor_unitario': 'R$ Unitário'})
            st.plotly_chart(fig_linha, use_container_width=True)
            
        with col2:
            df_pizza = df_filtrado.groupby('produto')['valor_total'].sum().reset_index()
            fig_pizza = px.pie(df_pizza, values='valor_total', names='produto', 
                               title="Distribuição do Gasto Total por Produto (R$)",
                               hole=0.3)
            st.plotly_chart(fig_pizza, use_container_width=True)

        # --- TABELA DE DADOS ---
        st.subheader(f"📋 Compras Encontradas ({len(df_filtrado)} registros)")
        # Remove a coluna temporária usada pra cálculo de data
        df_exibicao = df_filtrado.drop(columns=['data_emissao_dt'])
        st.dataframe(df_exibicao, use_container_width=True)
    else:
        st.warning("Nenhuma compra encontrada com os filtros selecionados.")

else:
    st.info("Nenhuma nota fiscal cadastrada ainda. Use a barra lateral para importar o primeiro arquivo XML!")
