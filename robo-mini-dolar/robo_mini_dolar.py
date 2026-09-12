# =============================================================================
# CORRECOES FINAS DE ESTRATEGIA (revisao pos-diagnostico dos replays 14/08 e 19/08)
# 1. Amostragem: ciclo FIXO de 300 s (5 min) em TODAS as faixas de horario.
#    A amostragem fina de abertura (45 s / 120 s) foi revertida por decisao
#    operacional — o app analisava praticamente sem parar.
# 2. Momentum com confirmacao: 'forte' exige inclinacao da MM9 na mesma direcao
#    e a direcao so inverte depois de 2 leituras — fim do alta_forte/baixa_forte
#    alternando a cada 70 segundos.
# 3. Gatekeeper virou filtro de ENTRADA, nao de DIRECAO: momentum forte bloqueia
#    somente a operacao CONTRA o movimento ou a entrada estirada da MM9.
# 4. Trava de falso rompimento so atua quando a entrada persegue a ponta do range.
# 5. Conviccao: penalidade de momentum forte deixa de punir a entrada a favor;
#    direcao confirmada e alinhada vira 'AGUARDAR PULLBACK' em vez de 'NAO OPERAR'.
# 6. Geometria: sem direcao definida nao existe alvo/stop — em ESPERA o painel
#    mostra referencia explicita, nunca alvo de compra para vies de venda.
# 7. Fonte unica de verdade: painel e CSV leem a MESMA classificacao da leitura.
# 8. Codigo do ativo canonico (WDOU26 / WDO26 / WDO -> um unico nome por sessao).
# =============================================================================
# REVISAO POS-REPLAY 14/08 (segunda passagem — 08:56 as 09:39)
# A. Leitura MANUAL fora do ciclo de 300 s informa, mas NAO entra na serie:
#    era a leitura de 68 s que virava o regime e cravava momentum forte.
# B. delta_3 exige janela de 3 leituras de verdade; com historico curto ele
#    repetia delta_preco e a confirmacao de momentum ficava sem base.
# C. Historico de leituras persistido em disco por ativo: reinicio do app
#    deixava a serie com 2 pontos e zerava a confirmacao.
# D. Codigo do ativo normalizado ANTES de indexar historico e gravar log.
# E. Em ESPERA a geometria e REFERENCIA derivada do vies — nunca alvo de
#    compra para leitura com vies de venda; sem direcao, sem alvo/stop.
# F. Conviccao com ESCALA UNICA (a menor entre veredito e ponderada) e piso
#    de direcao: abaixo de 30% o veredito nao aponta lado nenhum.
# G. Gatekeeper: momentum forte nao bloqueia entrada A FAVOR e no preco;
#    bloqueio na ponta do range e rotulado como range, nao como momentum.
# H. Volume: valor financeiro lido no campo de contratos e descartado.
# I. Abertura fora do intervalo minima-maxima e descartada na validacao.
# =============================================================================
import streamlit as st
import pandas as pd
import csv
import json
import re
import os
import time
import base64
import requests
import threading
import ctypes
import xml.etree.ElementTree as ET
from io import BytesIO
from datetime import datetime, timedelta
from PIL import Image
import pygetwindow as gw
import win32gui
import win32ui
import winsound
import pythoncom
import win32com.client
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# =========================
# CONFIGURACOES
# =========================
CHAVE_OPENROUTER = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_OPENROUTER = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash").strip()

def validar_config_openrouter():
    if not CHAVE_OPENROUTER:
        raise RuntimeError("A variável de ambiente OPENROUTER_API_KEY não foi definida.")

def chamar_openrouter(partes, temperature=0.0, timeout=40):
    validar_config_openrouter()
    headers = {
        "Authorization": f"Bearer {CHAVE_OPENROUTER}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODELO_OPENROUTER,
        "messages": [{"role": "user", "content": partes}],
        "temperature": temperature,
    }
    try:
        res = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        res.raise_for_status()
        data = res.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        st.session_state["ultimo_retorno_ia_bruto"] = content
        st.session_state["ultimo_erro_ia"] = ""
        return content
    except requests.exceptions.RequestException as e:
        st.session_state["ultimo_erro_ia"] = f"Erro HTTP/OpenRouter: {e}"
        return None
    except Exception as e:
        st.session_state["ultimo_erro_ia"] = f"Erro inesperado: {e}"
        return None

HISTORICO_CSV = "historico_trades_detalhado.csv"
MACRO_JSON = "mercado_macro.json"
DADOS_TELA_JSON = "dados_tela_profit.json"
FECHAMENTO_JSON = "fechamento_anterior.json"

# Janela de observacao da abertura: nenhum gatilho antes disso.
# O robo apenas descreve onde abriu, o gap contra o fechamento anterior e a
# tendencia que se forma. So depois libera compra ou venda.
MINUTOS_OBSERVACAO_ABERTURA = 5
HORA_ABERTURA_MERCADO = "09:00"

# =============================================================================
# JANELA OPERACIONAL — o app costuma ser ligado as 07h, mas so ha necessidade
# de analisar a partir das 08:55. Fora da janela o sistema fica em repouso:
# faz UMA leitura de verificacao ao ligar (para confirmar captura de tela,
# book, macro e som) e depois nao consome mais nada ate a janela abrir.
# =============================================================================
JANELA_OPERACIONAL_INICIO = "08:55"
JANELA_OPERACIONAL_FIM = "18:10"
# Refresh lento enquanto o sistema esta em repouso (fora da janela).
INTERVALO_REFRESH_REPOUSO_MS = 60000
# Minutos antes da abertura da janela em que o refresh volta ao normal, para
# o primeiro ciclo das 08:55 nao atrasar.
MIN_PRE_AQUECIMENTO_JANELA = 3

INTERVALO_ANALISE_SEGUNDOS = 300
INTERVALO_MACRO_SEGUNDOS = 300

# ---- AMOSTRAGEM: CICLO FIXO DE 5 MINUTOS ----
# Uma leitura a cada 300 s em TODAS as faixas de horario. A amostragem fina de
# abertura foi revertida por decisao operacional: o sistema analisava sem parar.
INTERVALO_ANALISE_ABERTURA_SEGUNDOS = 300
INTERVALO_ANALISE_MANHA_SEGUNDOS = 300
FIM_ABERTURA_MIN = 10 * 60
FIM_MANHA_MIN = 11 * 60

# ---- FILTROS DE SENSIBILIDADE (ajuste fino de entrada) ----
# 1. Piso absoluto do score: 3 autorizava entrada com pouca convergencia.
# Piso reduzido de 4 para 3: no dia 28/08 o piso 4 travou 65 das 119 leituras
# ("score 1/4" em 35 delas) e houve acerto de alvo com score baixo. Os filtros
# de setup (reversao, pullback, absorcao) fazem a selecao melhor que o score.
SCORE_MINIMO_ABSOLUTO = 3
# 2. Fluxo: saldo de agressao exigido, ou vies de fluxo direcional alinhado.
#    Fluxo neutro/indefinido deixa de ser aceito.
# Piso reduzido de 65 para 58: no replay de 26/08 o mercado rodou em 60% e o
# filtro barrou 57 leituras, entre elas 4 que atingiram o alvo.
SALDO_AGRESSAO_MINIMO = 58.0
# Pontos de agressao dispensados quando o setup ja tem reversao no extremo
# somada a pullback ou absorcao — os dois indicadores de maior acerto medido.
TOLERANCIA_FLUXO_ANCORADO = 10.0
# Fluxo morno passou a PENALIZAR o score em vez de vetar a entrada. So veta
# quando o fluxo esta claramente CONTRA a direcao pretendida.
PENALIDADE_FLUXO_MORNO = 1
# Distancia da agressao ao piso a partir da qual o fluxo e considerado contra.
MARGEM_FLUXO_CONTRARIO = 12.0
EXIGE_FLUXO_DIRECIONAL = True
# 3. Gatekeeper de book: +15% de respirabilidade na distancia tolerada.
FATOR_TOLERANCIA_BOOK = 1.15
DISTANCIA_OFERTANTE_BASE = 15.0
DISTANCIA_OFERTANTE_TOLERADA = round(DISTANCIA_OFERTANTE_BASE * FATOR_TOLERANCIA_BOOK, 2)

# Distancia maxima da MM9 para considerar a entrada "no preco".
# Elevado de 5,5 para 7,0: no pregao de 02/09 a distancia media ficou acima de
# 18 pts e o limite antigo marcava "entrada tardia" em praticamente toda leitura.
LIMITE_DIST_MM9_ENTRADA = 7.0
# Distancia a partir da qual a entrada e realmente vetada (antes qualquer valor
# acima de 5,5 pts virava espera, mesmo com o setup ancorado).
LIMITE_DIST_MM9_VETO = 9.0
# O veto ESCALA com a amplitude do dia: 9 pts fixos barraram 6 entradas com
# 18 a 28 pts de distancia num pregao de 67 pts. Fracao da amplitude usada
# como veto, com piso no limite fixo.
FRACAO_AMPLITUDE_VETO_MM9 = 0.30
LIMITE_DIST_MM9_VETO_MAX = 30.0


def limite_veto_mm9(amplitude_dia=0.0):
    """Distancia da MM9 que realmente veta a entrada, escalada pelo dia.

    Dia estreito mantem o limite fixo; dia amplo tolera mais distancia, porque
    30 pts de MM9 num pregao de 70 pts e a tendencia normal, nao exagero.
    """
    amp = num(amplitude_dia)
    if amp <= 0:
        return LIMITE_DIST_MM9_VETO
    return round(max(LIMITE_DIST_MM9_VETO,
                     min(LIMITE_DIST_MM9_VETO_MAX, amp * FRACAO_AMPLITUDE_VETO_MM9)), 2)
# Leituras na mesma direcao exigidas para confirmar o momentum.
MIN_LEITURAS_CONFIRMA_MOMENTUM = 2
# Fracao do ciclo abaixo da qual a leitura e considerada fora de ciclo
# (informa o painel, mas nao entra na serie de historico/momentum).
FRACAO_CICLO_LEITURA_VALIDA = 0.6
# Piso de conviccao para o veredito apontar um lado.
PISO_CONVICCAO_DIRECAO = 30
# Teto de conviccao exibida quando NAO ha gatilho armado. Impede que uma leitura
# em ESPERA apareca com 100% e seja lida como ordem de execucao.
TETO_CONVICCAO_SEM_GATILHO = 60

# =============================================================================
# AGENDA MACRO — horarios de Brasilia em que sai indicador de peso.
# dia_semana: None = todo dia util | 0=segunda ... 4=sexta
# dia_mes: lista de dias do mes (aproximacao para indicador mensal)
# peso: 3 = move o dolar sozinho | 2 = relevante | 1 = contexto
# =============================================================================
AGENDA_MACRO = [
    {"hora": "09:30", "nome": "CPI / PPI / PCE / Payroll (EUA)", "peso": 3, "dia_semana": None,
     "dia_mes": [1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15, 26, 27, 28, 29, 30, 31]},
    {"hora": "09:30", "nome": "Pedidos de auxilio-desemprego (EUA)", "peso": 2, "dia_semana": 3, "dia_mes": None},
    {"hora": "10:45", "nome": "PMI S&P Global (EUA)", "peso": 2, "dia_semana": None, "dia_mes": [21, 22, 23, 24, 25]},
    {"hora": "11:00", "nome": "ISM / Confianca do consumidor (EUA)", "peso": 3, "dia_semana": None,
     "dia_mes": [1, 2, 3, 4, 5, 25, 26, 27, 28, 29, 30, 31]},
    {"hora": "09:00", "nome": "IPCA / IGP-M / dados IBGE (Brasil)", "peso": 2, "dia_semana": None,
     "dia_mes": [8, 9, 10, 11, 12, 27, 28, 29, 30]},
    {"hora": "10:00", "nome": "Fluxo cambial / leilao Bacen", "peso": 1, "dia_semana": None, "dia_mes": None},
    {"hora": "15:00", "nome": "Decisao do FOMC", "peso": 3, "dia_semana": 2, "dia_mes": [17, 18, 19, 20, 21]},
    {"hora": "15:30", "nome": "Coletiva do FOMC", "peso": 3, "dia_semana": 2, "dia_mes": [17, 18, 19, 20, 21]},
    {"hora": "18:30", "nome": "Decisao do Copom", "peso": 3, "dia_semana": 2, "dia_mes": None},
]

# Minutos ANTES do evento em que o robo para de armar entrada nova.
MINUTOS_BLOQUEIO_PRE_EVENTO = 10
# Minutos DEPOIS do evento em que o robo analisa em ciclo acelerado.
MINUTOS_JANELA_POS_EVENTO = 30
# Ciclo de captura: permanece 300 s em TODA faixa de horario, inclusive em
# janela de evento macro. O evento nao acelera o ciclo; ele apenas ADICIONA uma
# analise extra logo apos o anuncio.
INTERVALO_ANALISE_EVENTO_SEGUNDOS = 300
# Segundos apos o horario do anuncio em que a analise extra e disparada.
SEGUNDOS_APOS_ANUNCIO = 15
# Janela de tolerancia para capturar o disparo. Precisa ser MAIOR que o refresh
# normal, senao o instante do anuncio passa entre dois reruns.
JANELA_DISPARO_ANUNCIO_SEG = 90
# Refresh do app em regime normal. 5 s reexecutava o script inteiro antes de a
# tela terminar de desenhar — o painel nunca aparecia.
INTERVALO_REFRESH_APP_MS = 30000
# Refresh fino, usado SOMENTE nos minutos ao redor de um anuncio da agenda.
INTERVALO_REFRESH_ANUNCIO_MS = 5000
# Minutos antes/depois do anuncio em que vale o refresh fino.
MIN_ANTES_REFRESH_FINO = 3
MIN_DEPOIS_REFRESH_FINO = 2
# Minutos apos o evento em que a volatilidade ainda distorce o book.
MINUTOS_RUIDO_POS_EVENTO = 3

# =============================================================================
# COLETA WEB DE MACRO — funciona SEM nenhuma tela aberta.
# Tudo aqui e requisicao HTTP direta as APIs publicas; nao depende de captura
# de janela, do Profit nem do navegador. Basta o app estar rodando.
# Cada indicador tem CADEIA DE FONTES: se a primeira falhar, tenta a proxima.
# =============================================================================
# Chaves das fontes macro. A variavel de ambiente tem prioridade; o valor
# embutido e o padrao para o app funcionar sem configuracao previa.
FMP_API_KEY = os.getenv("FMP_API_KEY", "PA5eToagbxyHZgZqZQCQEGfyqhLth4Pl").strip()
FRED_API_KEY = os.getenv("FRED_API_KEY", "b38e2f9e686973f1aa2058407de8be63").strip()
# Endpoint novo da FMP (stable). O /api/v3 continua como alternativa.
FMP_BASE_STABLE = "https://financialmodelingprep.com/stable"

# Series do Banco Central (SGS) — nao exigem chave.
BCB_SERIES = {
    "PTAX_VENDA": 1,        # dolar comercial venda
    "SELIC_META": 432,
    "IPCA_MES": 433,
    "IGPM_MES": 189,
}

# Series do FRED — DXY, VIX e PMI/ISM oficiais.
FRED_SERIES = {
    "DXY": "DTWEXBGS",          # indice amplo do dolar
    "VIX": "VIXCLS",
    # MANEMP era emprego industrial, nao o indice ISM: o PMI vinha vazio em
    # 100% das linhas. NAPM/NAPMPI sao as series de PMI de fato.
    # NAPM/NAPMPI foram descontinuadas no FRED e voltavam vazias em 100% das
    # leituras. As series abaixo continuam publicadas.
    "PMI_ISM_MANUFATURA": "IPMAN",
    "PMI_SENTIMENTO": "UMCSENT",
    "TREASURY_10A": "DGS10",
    "FED_FUNDS": "DFF",
}

# Endpoints das fontes, em ordem de preferencia por indicador.
FONTES_MACRO_WEB = {
    "PTAX":  ["bcb", "fmp", "investing"],
    "DXY":   ["fred", "fmp", "tradingeconomics", "investing"],
    "VIX":   ["fred", "fmp", "investing"],
    "EWZ":   ["fmp", "investing", "tradingeconomics"],
    "PMI":   ["tradingeconomics", "fred", "investing"],
}

URLS_FONTES_MACRO = {
    "bcb_sgs": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados/ultimos/{n}?formato=json",
    "bcb_sgs_periodo": ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
                        "?formato=json&dataInicial={ini}&dataFinal={fim}"),
    "bcb_ptax_dia": ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
                     "CotacaoDolarDia(dataCotacao=@dataCotacao)?@dataCotacao='{data}'"
                     "&$top=1&$format=json&$select=cotacaoCompra,cotacaoVenda,dataHoraCotacao"),
    "fred_obs": ("https://api.stlouisfed.org/fred/series/observations?series_id={serie}"
                 "&api_key={key}&file_type=json&sort_order=desc&limit={n}"),
    "fmp_stable_quote": FMP_BASE_STABLE + "/quote?symbol={ticker}&apikey={key}",
    "fmp_quote": "https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={key}",
    "fmp_hist": ("https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
                 "?from={ini}&to={fim}&apikey={key}"),
    "fmp_calendario": ("https://financialmodelingprep.com/api/v3/economic_calendar"
                       "?from={ini}&to={fim}&apikey={key}"),
    "te_indicador": "https://tradingeconomics.com/united-states/{slug}",
    "te_calendario": "https://tradingeconomics.com/calendar",
    "investing_calendario": "https://br.investing.com/economic-calendar/",
    "investing_indice": "https://br.investing.com/indices/{slug}",
}

# Validade do cache de cada indicador, em segundos.
TTL_CACHE_MACRO = {
    "PTAX": 3600,     # PTAX fecha uma vez por dia
    "DXY": 900,
    "VIX": 900,
    "EWZ": 900,
    "PMI": 21600,     # indicador mensal
    "CALENDARIO": 3600,
}

ARQ_CACHE_MACRO_WEB = "cache_macro_web.json"
TIMEOUT_HTTP_MACRO = 12
# Contratos plausiveis em um candle: acima disso o campo trouxe valor financeiro.
LIMITE_CONTRATOS_PLAUSIVEL = 200000
# Posicao no range a partir da qual a entrada persegue a ponta do dia.
PONTA_RANGE_COMPRA = 85.0
PONTA_RANGE_VENDA = 15.0
# Arquivo de persistencia da serie de leituras (sobrevive a reinicio do app).
ARQ_HIST_LEITURAS = "hist_leituras.json"


def _min_do_dia(hora_str):
    try:
        partes = str(hora_str).strip().split(":")
        return int(partes[0]) * 60 + int(partes[1])
    except Exception:
        return None


def _agenda_do_dia(agora=None):
    """Eventos macro validos para a data de hoje."""
    agora = agora or datetime.now()
    dia_semana, dia_mes = agora.weekday(), agora.day
    if dia_semana > 4:
        return []
    validos = []
    for ev in AGENDA_MACRO:
        if ev.get("dia_semana") is not None and ev["dia_semana"] != dia_semana:
            continue
        if ev.get("dia_mes") and dia_mes not in ev["dia_mes"]:
            continue
        validos.append(ev)
    return validos


def janela_evento_macro(agora=None):
    """Situacao da leitura atual em relacao a agenda macro.

    Devolve dict com:
      fase      — 'fora' | 'pre' | 'ruido' | 'pos'
      evento    — nome do indicador
      peso      — 1 a 3
      minutos   — minutos para o evento (negativo) ou desde o evento (positivo)
      bloqueia  — nao armar entrada nova agora
      acelera   — usar ciclo curto de captura
    """
    agora = agora or datetime.now()
    minuto_agora = agora.hour * 60 + agora.minute
    saida = {"fase": "fora", "evento": "", "peso": 0, "minutos": None,
             "bloqueia": False, "acelera": False, "resumo": ""}
    melhor = None
    for ev in _agenda_do_dia(agora):
        m_ev = _min_do_dia(ev["hora"])
        if m_ev is None:
            continue
        delta = minuto_agora - m_ev
        if -MINUTOS_BLOQUEIO_PRE_EVENTO <= delta <= MINUTOS_JANELA_POS_EVENTO:
            if melhor is None or ev["peso"] > melhor[0]["peso"]:
                melhor = (ev, delta)
    if not melhor:
        return saida
    ev, delta = melhor
    saida["evento"] = ev["nome"]
    saida["peso"] = int(ev["peso"])
    saida["minutos"] = int(delta)
    if delta < 0:
        saida["fase"] = "pre"
        saida["bloqueia"] = ev["peso"] >= 2
        saida["acelera"] = True
        saida["resumo"] = f"{ev['nome']} em {abs(delta)} min — nao abrir posicao nova."
    elif delta <= MINUTOS_RUIDO_POS_EVENTO:
        saida["fase"] = "ruido"
        saida["bloqueia"] = ev["peso"] >= 2
        saida["acelera"] = True
        saida["resumo"] = f"{ev['nome']} saiu ha {delta} min — book distorcido, aguardar acomodar."
    else:
        saida["fase"] = "pos"
        saida["bloqueia"] = False
        saida["acelera"] = True
        saida["resumo"] = f"{ev['nome']} ha {delta} min — janela de direcao definida."
    return saida


def macro_deve_coletar_agora(agora=None):
    """True quando a leitura cai num horario de agenda (ou na virada de cache).

    Regra: coleta ao ligar, a cada 5 min dentro de janela de evento, e uma vez
    por hora fora dela. Assim o robo busca o indicador EXATAMENTE nos horarios
    de CPI/PCE/Payroll 09:30, PMI 10:45, ISM 11:00, IPCA 09:00, FOMC 15:00 e
    15:30 e Copom 18:30, sem ficar batendo nos sites o dia inteiro.
    """
    agora = agora or datetime.now()
    ultima = st.session_state.get("ultima_coleta_macro_web")
    try:
        ultima_dt = datetime.strptime(str(ultima), "%Y-%m-%d %H:%M:%S") if ultima else None
    except Exception:
        ultima_dt = None
    if ultima_dt is None:
        return True, "primeira coleta da sessao"

    jan = janela_evento_macro(agora)
    decorrido = (agora - ultima_dt).total_seconds()
    if jan.get("fase") in ("pre", "ruido", "pos"):
        if decorrido >= 300:
            return True, f"janela de {jan.get('evento', 'evento macro')}"
        return False, ""
    if decorrido >= 3600:
        return True, "atualizacao horaria"
    return False, ""


def atualizar_macro_agendado(agora=None, forcar=False):
    """Dispara a coleta web quando for a hora. Chamar a cada ciclo de analise."""
    agora = agora or datetime.now()
    if st.session_state.get("modo_replay_ativo") and not forcar:
        return {"coletou": False, "motivo": "replay: coleta ao vivo desligada"}
    # Fora da janela nao ha decisao a tomar: nao gasta requisicao nas fontes.
    if not forcar and not dentro_janela_operacional(agora):
        return {"coletou": False, "motivo": "fora da janela operacional"}
    deve, motivo = (True, "forcado") if forcar else macro_deve_coletar_agora(agora)
    if not deve:
        return {"coletou": False, "motivo": ""}
    try:
        web = coletar_macro_web()
    except Exception as e:
        st.session_state["ultimo_erro_macro_web"] = str(e)
        return {"coletou": False, "motivo": "falha na coleta"}
    base = _ler_macro_arquivo() or {}
    for k, v in web.items():
        if k not in ("fontes", "indisponiveis", "completo", "timestamp", "data_referencia"):
            if v is not None:
                base[k] = v
    base["macro_fontes"] = web.get("fontes", {})
    base["macro_indisponiveis"] = web.get("indisponiveis", [])
    base["macro_indisponiveis_essenciais"] = web.get("indisponiveis_essenciais", [])
    base["macro_completo"] = bool(web.get("completo"))
    base["macro_timestamp"] = web.get("timestamp", "")
    # Guarda a leitura anterior de DXY e EWZ: sem ela a variacao percentual
    # nunca era calculada e esses dois indicadores nao pontuavam.
    _ant = _ler_macro_arquivo() or {}
    for _k in ("DXY", "EWZ"):
        _v_novo, _v_ant = num(web.get(_k)), num(_ant.get(_k))
        if _v_novo > 0 and _v_ant > 0 and abs(_v_novo - _v_ant) > 1e-9:
            base[_k + "_ANTERIOR"] = _v_ant
    try:
        with open(MACRO_JSON, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    st.session_state["ultima_coleta_macro_web"] = agora.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["macro_web_resumo"] = {
        "fontes": web.get("fontes", {}),
        "indisponiveis": web.get("indisponiveis", []),
        "hora": agora.strftime("%H:%M:%S"),
    }
    return {"coletou": True, "motivo": motivo, "indisponiveis": web.get("indisponiveis", [])}


def macro_para_replay(data_replay):
    """Macro da DATA do replay, quando a fonte tem historico.

    BCB, FRED e FMP respondem por data; raspagem de pagina nao. O que nao vier
    fica marcado como indisponivel para NAO pontuar a favor nem contra.
    """
    if not data_replay:
        return {"disponivel": False, "motivo": "sem data de replay", "indisponiveis": ["todos"]}
    chave = f"replay::{str(data_replay)[:10]}"
    cache = _cache_macro_ler().get(chave)
    if isinstance(cache, dict) and cache.get("dados"):
        return cache["dados"]
    dados = coletar_macro_web(data_ref=data_replay)
    dados["disponivel"] = bool(dados.get("PTAX") or dados.get("DXY") or dados.get("VIX"))
    dados["motivo"] = ("" if dados["disponivel"]
                       else "nenhuma fonte historica respondeu para a data do replay")
    cache_all = _cache_macro_ler()
    cache_all[chave] = {"dados": dados, "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _cache_macro_gravar(cache_all)
    return dados


def proximo_evento_macro(agora=None):
    """Proximo indicador do dia, para exibir no painel."""
    agora = agora or datetime.now()
    minuto_agora = agora.hour * 60 + agora.minute
    futuros = []
    for ev in _agenda_do_dia(agora):
        m_ev = _min_do_dia(ev["hora"])
        if m_ev is not None and m_ev >= minuto_agora:
            futuros.append((m_ev - minuto_agora, ev))
    if not futuros:
        return {"nome": "", "hora": "", "peso": 0, "faltam": None}
    faltam, ev = sorted(futuros, key=lambda t: t[0])[0]
    return {"nome": ev["nome"], "hora": ev["hora"], "peso": int(ev["peso"]), "faltam": int(faltam)}


def vies_macro_consolidado(macro=None):
    """Converte o painel macro (PMI, DXY, EWZ, VIX, PTAX) num vies unico para o WDO.

    Dolar sobe quando: PMI/inflacao dos EUA acima do esperado, DXY subindo,
    EWZ caindo, VIX subindo (aversao a risco).
    """
    macro = macro or ler_dados_macro()
    pontos, fatores = 0, []

    # Dado ausente NAO vale como sinal. No replay, ou quando a coleta web falha,
    # o macro entra como neutro em vez de empurrar a direcao com valor velho.
    _indisp = list((macro or {}).get("macro_indisponiveis", []) or [])
    _indisp_ess = list((macro or {}).get("macro_indisponiveis_essenciais", []) or [])
    # Falta de PMI (mensal) NAO invalida o macro: DXY, VIX, EWZ e PTAX bastam.
    _sem_essenciais = bool(_indisp_ess) or not any(
        num((macro or {}).get(k)) > 0 for k in ("DXY", "VIX", "EWZ", "PTAX"))
    if _sem_essenciais or (macro or {}).get("disponivel") is False:
        return {"vies": "neutro", "forca": "neutro", "pontos": 0,
                "fatores": ["macro indisponivel para a data — sem peso na decisao"],
                "indisponivel": True,
                "resumo": "Macro indisponivel — nao pontua"}

    pmi = peso_pmi_eua(macro)
    if pmi.get("peso"):
        pontos += int(pmi["peso"])
        fatores.append(pmi.get("descricao", ""))

    dxy = num(macro.get("DXY"))
    dxy_ant = num(macro.get("DXY_ANTERIOR"))
    # Sem leitura anterior o DXY deixava de pontuar. O NIVEL tambem informa:
    # acima de 105 o dolar esta forte no mundo; abaixo de 97, fraco.
    if dxy > 0 and dxy_ant <= 0:
        if dxy >= 105:
            pontos += 1; fatores.append(f"DXY em {dxy:.2f} — dólar forte no mundo")
        elif dxy <= 97:
            pontos -= 1; fatores.append(f"DXY em {dxy:.2f} — dólar fraco no mundo")
    if dxy > 0 and dxy_ant > 0:
        var = (dxy - dxy_ant) / dxy_ant * 100
        if var >= 0.25:
            pontos += 2; fatores.append(f"DXY +{var:.2f}% — dolar forte no mundo")
        elif var <= -0.25:
            pontos -= 2; fatores.append(f"DXY {var:.2f}% — dolar fraco no mundo")

    ewz = num(macro.get("EWZ"))
    ewz_ant = num(macro.get("EWZ_ANTERIOR"))
    if ewz > 0 and ewz_ant > 0:
        var = (ewz - ewz_ant) / ewz_ant * 100
        if var <= -0.60:
            pontos += 1; fatores.append(f"EWZ {var:.2f}% — Brasil vendido, favorece o dolar")
        elif var >= 0.60:
            pontos -= 1; fatores.append(f"EWZ +{var:.2f}% — Brasil comprado, pressiona o dolar")

    vix = num(macro.get("VIX"))
    if vix >= 22:
        pontos += 1; fatores.append(f"VIX {vix:.1f} — aversao a risco")
    elif 0 < vix <= 14:
        pontos -= 1; fatores.append(f"VIX {vix:.1f} — apetite a risco")

    if pontos >= 3:
        vies, forca = "compra", "forte"
    elif pontos >= 1:
        vies, forca = "compra", "moderado"
    elif pontos <= -3:
        vies, forca = "venda", "forte"
    elif pontos <= -1:
        vies, forca = "venda", "moderado"
    else:
        vies, forca = "neutro", "neutro"

    if _indisp:
        fatores.append("sem leitura de: " + ", ".join(str(x) for x in _indisp))
        if forca == "forte":
            forca = "moderado"      # dado parcial nao autoriza peso maximo
    # 'indisponivel' passa a significar: faltam os ESSENCIAIS. Ausencia do PMI
    # apenas rebaixa a forca, nao zera o macro.
    return {"vies": vies, "forca": forca, "pontos": int(pontos),
            "fatores": fatores, "indisponivel": bool(_indisp_ess),
            "parcial": bool(_indisp),
            "resumo": f"Macro {forca} para {vies} ({pontos:+d})" if vies != "neutro"
                      else "Macro sem direcao definida"}


def intervalo_analise_atual(hora_str=None):
    """Intervalo de captura: 300 s fixos, em QUALQUER faixa de horario.
    A janela de evento macro nao encurta o ciclo — ela gera uma analise extra
    15 s depois do anuncio, tratada por disparo_pos_anuncio()."""
    return INTERVALO_ANALISE_SEGUNDOS


def dentro_janela_operacional(agora=None):
    """True quando o horario esta dentro de 08:55–18:10."""
    agora = agora or datetime.now()
    ini = _min_do_dia(JANELA_OPERACIONAL_INICIO)
    fim = _min_do_dia(JANELA_OPERACIONAL_FIM)
    if ini is None or fim is None:
        return True
    minuto = agora.hour * 60 + agora.minute
    return ini <= minuto <= fim


def minutos_para_janela(agora=None):
    """Minutos que faltam para a janela abrir. Negativo depois do fechamento."""
    agora = agora or datetime.now()
    ini = _min_do_dia(JANELA_OPERACIONAL_INICIO)
    fim = _min_do_dia(JANELA_OPERACIONAL_FIM)
    minuto = agora.hour * 60 + agora.minute
    if ini is None or fim is None:
        return 0
    if minuto < ini:
        return ini - minuto
    if minuto > fim:
        return -(minuto - fim)
    return 0


def estado_janela_operacional(agora=None):
    """Situacao da sessao em relacao a janela de trabalho.

    fase: 'pre' (antes das 08:55) | 'ativa' | 'pos' (depois das 18:10)
    """
    agora = agora or datetime.now()
    dentro = dentro_janela_operacional(agora)
    falta = minutos_para_janela(agora)
    if dentro:
        fase, resumo = "ativa", "Janela operacional ativa."
    elif falta > 0:
        h, m = divmod(falta, 60)
        _t = f"{h}h{m:02d}min" if h else f"{m} min"
        fase = "pre"
        resumo = (f"Fora da janela — análises começam às "
                  f"{JANELA_OPERACIONAL_INICIO} (em {_t}).")
    else:
        fase = "pos"
        resumo = (f"Fora da janela — pregão encerrado às "
                  f"{JANELA_OPERACIONAL_FIM}.")
    return {"fase": fase, "dentro": dentro, "minutos_para_abrir": max(0, falta),
            "resumo": resumo,
            "inicio": JANELA_OPERACIONAL_INICIO, "fim": JANELA_OPERACIONAL_FIM}


def precisa_leitura_de_ligacao(agora=None):
    """Uma unica leitura de verificacao por dia, feita ao ligar o app.

    Serve para confirmar que captura de tela, book e macro respondem, sem
    iniciar o ciclo de 5 minutos antes da hora.
    """
    agora = agora or datetime.now()
    dia = agora.strftime("%Y-%m-%d")
    return str(st.session_state.get("leitura_ligacao_feita", "")) != dia


def registrar_leitura_de_ligacao(agora=None):
    agora = agora or datetime.now()
    st.session_state["leitura_ligacao_feita"] = agora.strftime("%Y-%m-%d")
    st.session_state["hora_leitura_ligacao"] = agora.strftime("%H:%M:%S")


def intervalo_refresh_atual(agora=None):
    """Milissegundos de refresh do app.

    Regime normal: 30 s — leve, deixa a tela renderizar por completo.
    Perto de um anuncio da agenda: 5 s, para acertar o instante + 15 s.
    """
    agora = agora or datetime.now()
    # Fora da janela operacional o app entra em repouso: refresh lento, sem
    # captura de tela e sem chamada de IA. Volta ao ritmo normal 3 min antes.
    try:
        if not dentro_janela_operacional(agora):
            if minutos_para_janela(agora) > MIN_PRE_AQUECIMENTO_JANELA:
                return INTERVALO_REFRESH_REPOUSO_MS
    except Exception:
        pass
    try:
        minuto_agora = agora.hour * 60 + agora.minute
        for ev in _agenda_do_dia(agora):
            m_ev = _min_do_dia(ev["hora"])
            if m_ev is None:
                continue
            delta = minuto_agora - m_ev
            if -MIN_ANTES_REFRESH_FINO <= delta <= MIN_DEPOIS_REFRESH_FINO:
                return INTERVALO_REFRESH_ANUNCIO_MS
    except Exception:
        pass
    return INTERVALO_REFRESH_APP_MS


def disparo_pos_anuncio(agora=None):
    """Analise extra 15 s depois do horario de um indicador da agenda.

    Roda UMA vez por evento por dia, em paralelo ao ciclo normal de 300 s.
    Devolve (deve_rodar, chave_do_evento, nome_do_evento).
    """
    agora = agora or datetime.now()
    # Copom as 18:30 cai FORA da janela: nao dispara analise.
    if not dentro_janela_operacional(agora):
        return False, "", ""
    disparados = st.session_state.get("disparos_anuncio_feitos")
    if not isinstance(disparados, dict):
        disparados = {}
    dia = agora.strftime("%Y-%m-%d")
    for ev in _agenda_do_dia(agora):
        m_ev = _min_do_dia(ev["hora"])
        if m_ev is None:
            continue
        alvo = agora.replace(hour=m_ev // 60, minute=m_ev % 60,
                             second=SEGUNDOS_APOS_ANUNCIO, microsecond=0)
        atraso = (agora - alvo).total_seconds()
        if 0 <= atraso <= JANELA_DISPARO_ANUNCIO_SEG:
            chave = f"{dia}::{ev['hora']}::{ev['nome']}"
            if chave not in disparados:
                return True, chave, ev["nome"]
    return False, "", ""


def registrar_disparo_anuncio(chave):
    """Marca o evento como ja analisado para nao repetir no mesmo dia."""
    d = st.session_state.get("disparos_anuncio_feitos")
    if not isinstance(d, dict):
        d = {}
    d[chave] = datetime.now().strftime("%H:%M:%S")
    st.session_state["disparos_anuncio_feitos"] = d

FONTES_EXTERNAS = {
    "Mini dolar": "https://br.tradingview.com/symbols/BMFBOVESPA-WDO1!/",
    "Noticias TradingView": "https://br.tradingview.com/news/economic-category/all/",
    "Noticias Trading Economics": "https://pt.tradingeconomics.com/stream",
    "Indices TradingView": "https://br.tradingview.com/markets/indices/",
    "Indices Trading Economics": "https://pt.tradingeconomics.com/stocks",
    "Futuros": "https://br.tradingview.com/markets/futures/quotes-all/",
    "Titulos do governo": "https://br.tradingview.com/markets/bonds/",
    "Economia mundial": "https://br.tradingview.com/markets/world-economy/",
    "DXY": "https://br.tradingview.com/symbols/TVC-DXY/",
    "EWZ": "https://br.tradingview.com/symbols/AMEX-EWZ/",
    "Calendario TradingView": "https://br.tradingview.com/economic-calendar/",
    "Calendario MQL5": "https://www.mql5.com/pt/economic-calendar",
    "Calendario Trading Economics": "https://pt.tradingeconomics.com/calendar",
    "Acoes": "https://pt.tradingeconomics.com/shares",
    "Moedas": "https://pt.tradingeconomics.com/currencies",
    "Mercadorias": "https://pt.tradingeconomics.com/commodities",
}

ESTRATEGIAS = {
    # amp_fibo: amplitude base para o alvo (reduzido de 5.0 para 3.0 — alvo ~4.8 pts em vez de 8.0)
    # stop_pts: stop ampliado de 5.0 para 6.5 pts para reduzir ERRO_STOP prematuros
    "Conservador": {
        "margem_vwap": 12.0, "rr_minimo": 1.2, "score_minimo_base": 5,
        "exige_vwap": True, "exige_mm200": True, "permite_pullback": False,
        "bloqueia_contra_tendencia": True, "amp_fibo": 3.0, "stop_pts": 6.5,
        "cor": "#2196F3", "descricao": "Alta precisao. Exige confluencia maxima.",
    },
    "Agressividade Média": {
        "margem_vwap": 20.0, "rr_minimo": 0.8, "score_minimo_base": 3,
        "exige_vwap": False, "exige_mm200": False, "permite_pullback": True,
        "bloqueia_contra_tendencia": True, "amp_fibo": 3.0, "stop_pts": 6.5,
        "cor": "#FF9800", "descricao": "Equilibrio entre oportunidades e seguranca.",
    },
    "Agressividade Alta": {
        "margem_vwap": 18.0, "rr_minimo": 1.0, "score_minimo_base": 2,
        "exige_vwap": False, "exige_mm200": False, "permite_pullback": True,
        "bloqueia_contra_tendencia": False, "amp_fibo": 3.0, "stop_pts": 6.5,
        "cor": "#F44336", "descricao": "Maxima captura de movimentos. Maior risco.",
    },
}

CSS_PROFISSIONAL = """
<style>
    .stApp { background-color: #0b0e14; color: #e8ecf3; }
    .block-container { padding-top: 1.1rem !important; }

    /* ---------- HERO: faixa de decisao no topo ---------- */
    .hero { border-radius:16px; padding:18px 22px; margin:6px 0 14px 0;
            border:2px solid #2d3561; background:linear-gradient(135deg,#131826,#0d1220);
            box-shadow:0 6px 24px rgba(0,0,0,.45); }
    .hero.compra { border-color:#00e676; background:linear-gradient(135deg,#04240f,#0a1a12); }
    .hero.venda  { border-color:#ff5252; background:linear-gradient(135deg,#2a0707,#1a0d0d); }
    .hero.espera { border-color:#ffd740; background:linear-gradient(135deg,#241d03,#171308); }
    .hero.neutro { border-color:#2d3561; }
    .hero .acao  { font-size:34px; font-weight:800; letter-spacing:2px; line-height:1.1; }
    .hero .sub   { font-size:13px; color:#a9b3c6; margin-top:4px; }
    .hero .linha { font-size:14px; margin-top:10px; line-height:1.9; }

    /* ---------- Cartoes de metrica ---------- */
    .metric-card { background:linear-gradient(135deg,#161b2b,#11172a); border:1px solid #232a45;
                   border-radius:12px; padding:14px 12px; text-align:center; margin:4px 0; }
    .metric-card .label { font-size:11px; color:#8892a4; text-transform:uppercase; letter-spacing:1px; }
    .metric-card .value { font-size:21px; font-weight:700; margin-top:4px; }
    .metric-card .value.green { color:#00e676; }
    .metric-card .value.red   { color:#ff5252; }
    .metric-card .value.blue  { color:#40c4ff; }
    .metric-card .value.gold  { color:#ffd740; }

    /* ---------- Badges e pilulas ---------- */
    .status-badge { display:inline-block; padding:4px 14px; border-radius:20px;
                    font-size:13px; font-weight:600; letter-spacing:1px; }
    .badge-armado    { background:#003300; color:#00e676; border:1px solid #00e676; }
    .badge-bloqueado { background:#330000; color:#ff5252; border:1px solid #ff5252; }
    .badge-espera    { background:#332200; color:#ffd740; border:1px solid #ffd740; }
    .badge-aguardando{ background:#161b2b; color:#8892a4; border:1px solid #232a45; }
    .pill { display:inline-block; padding:3px 10px; border-radius:14px; font-size:11px;
            font-weight:700; letter-spacing:.4px; margin:2px 6px 2px 0; }
    .pill.ok   { background:#04240f; color:#00e676; border:1px solid #00e676; }
    .pill.warn { background:#241d03; color:#ffd740; border:1px solid #ffd740; }
    .pill.bad  { background:#2a0707; color:#ff5252; border:1px solid #ff5252; }
    .pill.info { background:#04202e; color:#40c4ff; border:1px solid #40c4ff; }

    /* ---------- Escada do book (profundidade com agentes) ---------- */
    .book-wrap { background:linear-gradient(135deg,#0f1421,#0b0e17); border:1px solid #232a45;
                 border-radius:14px; padding:12px 14px; }
    .book-tit  { font-size:13px; font-weight:700; color:#40c4ff; letter-spacing:.5px;
                 margin-bottom:8px; display:flex; justify-content:space-between; align-items:center; }
    .book-head { display:grid; grid-template-columns:66px 84px 1fr 68px; gap:8px;
                 font-size:10px; color:#7d879b; text-transform:uppercase; letter-spacing:1px;
                 padding:0 6px 6px 6px; border-bottom:1px solid #232a45; }
    .book-row  { display:grid; grid-template-columns:66px 84px 1fr 68px; gap:8px;
                 align-items:center; padding:5px 6px; border-radius:6px; font-size:13px; }
    .book-row:hover { background:#151b2b; }
    .book-row .qt { font-weight:700; text-align:right; font-variant-numeric:tabular-nums; }
    .book-row .pr { font-weight:700; font-variant-numeric:tabular-nums; }
    .book-row .ag { color:#dfe5f0; font-size:12px; white-space:nowrap;
                    overflow:hidden; text-overflow:ellipsis; }
    .book-row .ag small { color:#7d879b; }
    .book-row.ask .qt, .book-row.ask .pr { color:#ff6b6b; }
    .book-row.bid .qt, .book-row.bid .pr { color:#00e676; }
    .book-bar { height:7px; border-radius:4px; }
    .book-bar.ask { background:linear-gradient(90deg,#ff5252,#7a1f1f); }
    .book-bar.bid { background:linear-gradient(90deg,#00e676,#0d5c33); }
    .book-mid { display:flex; justify-content:space-between; align-items:center; margin:8px 0;
                padding:7px 10px; border-radius:8px; background:#1a2138;
                border:1px dashed #40c4ff; font-size:12px; font-weight:700; color:#a9b3c6; }
    .book-mid .p { color:#40c4ff; font-size:17px; }

    /* ---------- Diversos ---------- */
    .regime-box { background:#161b2b; border-left:4px solid #40c4ff; border-radius:8px;
                  padding:12px 16px; margin:8px 0; font-size:14px; }
    .section-title { font-size:16px; font-weight:700; color:#40c4ff;
                     border-bottom:1px solid #232a45; padding-bottom:6px; margin:22px 0 12px 0; }
    .diag-box { background:#161b2b; border:1px solid #232a45; border-radius:10px;
                padding:14px; font-size:13px; line-height:1.6; color:#d0d6e0; }
    .sinal-9h { background:linear-gradient(135deg,#003300,#001a00); border:1px solid #00e676;
                border-radius:12px; padding:20px; margin:8px 0; }
    .sinal-9h h3 { color:#00e676; margin:0 0 8px 0; }
    .limiar-ok { color:#00e676; font-weight:700; }
    .limiar-ruim { color:#ff5252; font-weight:700; }
    .limiar-medio { color:#ffd740; font-weight:700; }
    div[data-testid="stTabs"] button { font-size:15px; font-weight:600; }
    div[data-testid="stExpander"] { border:1px solid #232a45; border-radius:10px; }
</style>
"""

# =========================
# ESTADO INICIAL
# =========================
st.set_page_config(
    page_title="AutoPro — Radar Institucional",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS_PROFISSIONAL, unsafe_allow_html=True)

if "historico_trades" not in st.session_state:
    st.session_state.historico_trades = []
    if os.path.exists(HISTORICO_CSV):
        try:
            df_init = pd.read_csv(HISTORICO_CSV)
            if "DataRegistro" in df_init.columns:
                df_init["_ord"] = pd.to_datetime(df_init["DataRegistro"], errors="coerce")
                df_init = df_init.sort_values("_ord", ascending=False).drop(columns=["_ord"])
            st.session_state.historico_trades = df_init.to_dict(orient="records")
        except Exception:
            st.session_state.historico_trades = []

defaults = {
    "estrategia_operacional": "Agressividade Média",
    "modo_replay": False,
    "usar_macro_no_replay": False,
    "replay_data": datetime.now().strftime("%Y-%m-%d"),
    "replay_hora": "09:00",
    "replay_seq": 0,
    "avancar_replay_auto": False,
    "analise_automatica": False,
    "disparos_anuncio_feitos": {},
    "ultimo_disparo_anuncio": "",
    "disparo_automatico": False,
    "bloquear_gatilho_repetido": True,
    "som_ativo": True,
    "som_mudanca_brusca": True,
    "historico_alertas": [],
    "hist_leituras": [],
    "hist_candles": [],
    "hist_assinatura_book": [],
    "ultimo_sinal_armado": {},
    "hist_fluxo": [],
    "pmi_ism_servicos": 0.0,
    "pmi_sp_servicos": 0.0,
    "pmi_manufatura": 0.0,
    "pmi_composto": 0.0,
    "estado_anterior_tendencia": {},
    "ultima_mudanca_brusca": "",
    "ultimo_ciclo_analise": 0.0,
    "ultimo_macro_update": 0.0,
    "ultimo_diagnostico": "Aguardando primeira analise...",
    "ultimo_status_gatilho": "AGUARDANDO",
    "ultimo_titulo_capturado": "Nenhuma captura ainda.",
    "ultimo_retorno_ia_bruto": "",
    "ultimo_erro_ia": "",
    "ultimos_dados_tela": {},
    "registrar_fechamento_ativo": False,
    "sinal_9h": {},
    "limiar_score": 3,
    "max_dia_manual": 0.0,
    "min_dia_manual": 0.0,
    "varal_contratos_totais": 5,
    "varal_ativo": True,
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================
# VIES DO DIA ANTERIOR
# =========================
def calcular_vies_fechamento(preco, ajuste, vwap, dxy, ewz, vix):
    if preco <= 0 or ajuste <= 0:
        return "indefinido"
    pc, pv = 0, 0
    if preco > ajuste: pc += 3
    elif preco < ajuste: pv += 3
    if vwap > 0:
        if preco > vwap: pc += 2
        elif preco < vwap: pv += 2
    try:
        if float(dxy) > 101: pc += 1
        elif float(dxy) < 99: pv += 1
    except Exception: pass
    try:
        if float(ewz) > 35: pv += 1
        elif float(ewz) < 32: pc += 1
    except Exception: pass
    try:
        if float(vix) > 20: pc += 1
        elif float(vix) < 13: pv += 1
    except Exception: pass
    if pc > pv + 1: return "comprador"
    if pv > pc + 1: return "vendedor"
    return "neutro"


def calcular_fibonacci_diario(maxima, minima):
    """
    Calcula os níveis de Fibonacci da amplitude máxima/mínima do dia.
    Usado para definir zonas de segurança no dia seguinte.
    """
    if maxima <= 0 or minima <= 0 or maxima <= minima:
        return {}
    amp = maxima - minima
    return {
        "amp": round(amp, 2),
        "nivel_0":    round(maxima, 2),
        "nivel_236":  round(maxima - amp * 0.236, 2),
        "nivel_382":  round(maxima - amp * 0.382, 2),
        "nivel_50":   round(maxima - amp * 0.500, 2),
        "nivel_618":  round(maxima - amp * 0.618, 2),
        "nivel_786":  round(maxima - amp * 0.786, 2),
        "nivel_100":  round(minima, 2),
    }


def salvar_fechamento_dia(preco, ajuste, vwap, dxy, ewz, vix, maxima=0.0, minima=0.0):
    # Sem maxima/minima informadas, usa o range acumulado do dia: era por isso
    # que o fechamento gravava 0 e as faixas do dia seguinte nasciam vazias.
    if not (maxima > minima > 0):
        _rg = st.session_state.get("ultimo_range_dia") or {}
        _mx, _mn = num(_rg.get("maxima", 0)), num(_rg.get("minima", 0))
        if _mx > _mn > 0:
            maxima, minima = _mx, _mn
    fib = calcular_fibonacci_diario(maxima, minima) if maxima > 0 and minima > 0 else {}
    # No replay a data do fechamento e a do pregao analisado, nao a de hoje:
    # gravar "hoje" fazia o dia seguinte ler faixas de outro pregao.
    try:
        _dt_fech = _data_referencia_leitura(st.session_state.get("ultimos_dados_tela"))
    except Exception:
        _dt_fech = datetime.now().strftime("%Y-%m-%d")
    dados = {
        "data": _dt_fech,
        "preco": preco, "ajuste": ajuste, "vwap": vwap,
        "dxy": dxy, "ewz": ewz, "vix": vix,
        "maxima_dia": maxima,
        "minima_dia": minima,
        "fibonacci_diario": fib,
        "vies": calcular_vies_fechamento(preco, ajuste, vwap, dxy, ewz, vix),
    }
    try:
        with open(FECHAMENTO_JSON, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception: pass
    return dados


# =============================================================================
# FAIXAS OPERACIONAIS — mapa de cores derivado do pregao ANTERIOR
# VERDE    : zona de compra (fundo do dia anterior, suportes)
# AMARELA  : zona neutra / observacao (meio do range, VWAP e ajuste)
# VERMELHA : zona de venda (topo do dia anterior, resistencias)
# =============================================================================
# Espessura de cada faixa como fracao da amplitude do dia anterior.
FRACAO_FAIXA_EXTREMA = 0.18     # verde e vermelha
FRACAO_FAIXA_NEUTRA = 0.14      # amarela em torno das ancoras


def dia_util_anterior(data_ref=None):
    """Data do pregao imediatamente anterior (pula sabado e domingo)."""
    try:
        if data_ref:
            d = datetime.strptime(str(data_ref)[:10], "%Y-%m-%d")
        else:
            d = datetime.now()
    except Exception:
        d = datetime.now()
    d = d - timedelta(days=1)
    while d.weekday() > 4:          # 5 = sabado, 6 = domingo
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _data_referencia_leitura(dados_tela=None):
    """Data do pregao que esta sendo analisado — no replay, a data do replay."""
    d = dados_tela or {}
    for chave in ("data_replay", "data"):
        v = str(d.get(chave, "") or "")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return v
    try:
        if st.session_state.get("modo_replay"):
            v = str(st.session_state.get("replay_data", "") or "")[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                return v
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%d")


def _range_do_historico_csv(data_alvo, ativo=""):
    """Maxima, minima e ajuste de UM dia especifico, lidos do log de trades.

    O historico e a unica fonte que sobrevive ao replay: guarda o pregao dia a
    dia, entao serve para montar as faixas de qualquer data.
    """
    try:
        if not os.path.exists(HISTORICO_CSV):
            return {}
        df = pd.read_csv(HISTORICO_CSV, low_memory=False)
        if df.empty or "DataEvento" not in df.columns:
            return {}
        _dia = df["DataEvento"].astype(str).str.slice(0, 10)
        sel = df[_dia == str(data_alvo)[:10]]
        if sel.empty:
            return {}
        if ativo and "Ativo" in sel.columns:
            _canon = ativo_canonico(ativo)
            _f = sel[sel["Ativo"].astype(str).str.startswith(str(_canon)[:3])]
            if not _f.empty:
                sel = _f

        def _mx(col):
            if col not in sel.columns:
                return 0.0
            v = pd.to_numeric(sel[col], errors="coerce").dropna()
            v = v[v > 0]
            return float(v.max()) if not v.empty else 0.0

        def _mn(col):
            if col not in sel.columns:
                return 0.0
            v = pd.to_numeric(sel[col], errors="coerce").dropna()
            v = v[v > 0]
            return float(v.min()) if not v.empty else 0.0

        def _ult(col):
            if col not in sel.columns:
                return 0.0
            v = pd.to_numeric(sel[col], errors="coerce").dropna()
            v = v[v > 0]
            return float(v.iloc[-1]) if not v.empty else 0.0

        maxima = max(_mx("RangeDiaMaxima"), _mx("Maxima"), _mx("PrecoEntrada"))
        _mins = [x for x in (_mn("RangeDiaMinima"), _mn("Minima"), _mn("PrecoEntrada")) if x > 0]
        minima = min(_mins) if _mins else 0.0
        return {"maxima": round(maxima, 2), "minima": round(minima, 2),
                "ajuste": round(_ult("Ajuste"), 2),
                "vwap": round(_ult("VWAP"), 2),
                "fechamento": round(_ult("PrecoEntrada"), 2),
                "leituras": int(len(sel)), "data": str(data_alvo)[:10]}
    except Exception:
        return {}


def referencia_pregao_anterior(dados_tela=None):
    """Maxima, minima e ajuste do DIA UTIL ANTERIOR ao pregao analisado.

    Ordem das fontes: range acumulado gravado para AQUELA data -> log de trades
    daquela data -> fechamento salvo (somente se for do mesmo dia).
    """
    d = dados_tela or {}
    data_hoje = _data_referencia_leitura(d)
    data_ant = dia_util_anterior(data_hoje)
    ativo = ativo_canonico(d.get("ativo", "")) or ""
    _p_ref = num(d.get("preco_atual", 0))

    def _coerente(mx, mn):
        """Referencia plausivel: ordenada, com amplitude util e na escala do preco."""
        if not (mx > mn > 0):
            return False
        if (mx - mn) < AMPLITUDE_MINIMA_RANGE:
            return False
        if _p_ref > 0 and abs(((mx + mn) / 2.0) - _p_ref) > (_p_ref * 0.04):
            return False
        return True

    # 0. LEITURA DE TELA — o Profit exibe o ajuste anterior e as linhas de
    #    maxima/minima do pregao passado. E a fonte mais fiel e a unica que
    #    acompanha a data do replay sem depender de historico gravado.
    _mx_t = num(d.get("maxima_anterior", 0))
    _mn_t = num(d.get("minima_anterior", 0))
    _aj_t = num(d.get("ajuste_anterior", 0))
    _dt_t = str(d.get("data_pregao_anterior", "") or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", _dt_t):
        _dt_t = data_ant
    if _coerente(_mx_t, _mn_t):
        _res_tela = {"maxima": round(_mx_t, 2), "minima": round(_mn_t, 2),
                     "ajuste": round(_aj_t, 2), "vwap": 0.0,
                     "data": _dt_t, "fonte": "tela_pregao_anterior"}
        # Guarda para as proximas leituras do mesmo pregao, caso a tela mude.
        try:
            _cache_pa = st.session_state.get("ref_pregao_anterior_tela")
            if not isinstance(_cache_pa, dict):
                _cache_pa = {}
            _cache_pa[f"{ativo or 'ATIVO'}::{data_hoje}"] = _res_tela
            st.session_state["ref_pregao_anterior_tela"] = _cache_pa
        except Exception:
            pass
        return _res_tela

    # 0b. Leitura de tela guardada nesta sessao para o MESMO pregao.
    try:
        _cache_pa = st.session_state.get("ref_pregao_anterior_tela") or {}
        _guardado = _cache_pa.get(f"{ativo or 'ATIVO'}::{data_hoje}")
        if isinstance(_guardado, dict) and _coerente(num(_guardado.get("maxima", 0)),
                                                     num(_guardado.get("minima", 0))):
            _g = dict(_guardado)
            _g["fonte"] = "tela_pregao_anterior (memoria)"
            return _g
    except Exception:
        pass

    # 1. Range acumulado da data exata do dia anterior.
    try:
        mapa = _carregar_range_dia()
        chaves = [k for k, v in mapa.items()
                  if isinstance(v, dict) and k.endswith("::" + data_ant)
                  and (not ativo or k.startswith(ativo[:3]))]
        for k in chaves:
            v = mapa[k]
            mx, mn = num(v.get("maxima", 0)), num(v.get("minima", 0))
            if mx > mn > 0:
                _h = _range_do_historico_csv(data_ant, ativo)
                return {"maxima": mx, "minima": mn,
                        "ajuste": num(_h.get("ajuste", 0)),
                        "vwap": num(_h.get("vwap", 0)),
                        "data": data_ant, "fonte": "range_acumulado"}
    except Exception:
        pass

    # 2. Log de trades da data do dia anterior.
    h = _range_do_historico_csv(data_ant, ativo)
    if num(h.get("maxima", 0)) > num(h.get("minima", 0)) > 0:
        h["fonte"] = "historico"
        return h

    # 3. Fechamento salvo — so vale se for justamente do dia anterior.
    try:
        fa = ler_fechamento_anterior() or {}
        if str(fa.get("data", ""))[:10] == data_ant:
            mx, mn = num(fa.get("maxima_dia", 0)), num(fa.get("minima_dia", 0))
            if mx > mn > 0:
                return {"maxima": mx, "minima": mn,
                        "ajuste": num(fa.get("ajuste", 0)),
                        "vwap": num(fa.get("vwap", 0)),
                        "data": data_ant, "fonte": "fechamento"}
    except Exception:
        pass

    # 4. Ultimo pregao com registro ANTES da data analisada (feriado, emenda).
    try:
        mapa = _carregar_range_dia()
        ants = []
        for k, v in mapa.items():
            if not isinstance(v, dict) or "::" not in k:
                continue
            _dk = k.split("::")[-1]
            if _dk < data_hoje and (not ativo or k.startswith(ativo[:3])):
                ants.append((_dk, v))
        if ants:
            _dk, v = sorted(ants, key=lambda t: t[0])[-1]
            mx, mn = num(v.get("maxima", 0)), num(v.get("minima", 0))
            if mx > mn > 0:
                _h = _range_do_historico_csv(_dk, ativo)
                return {"maxima": mx, "minima": mn,
                        "ajuste": num(_h.get("ajuste", 0)),
                        "vwap": num(_h.get("vwap", 0)),
                        "data": _dk, "fonte": "ultimo_pregao_registrado"}
    except Exception:
        pass

    # 5. Pregao ANTERIOR mais recente no historico do CSV. Nunca uma data
    #    POSTERIOR: o replay de 14/08 estava pegando 02/09 como referencia.
    try:
        if os.path.exists(HISTORICO_CSV):
            _dfh = pd.read_csv(HISTORICO_CSV, low_memory=False)
            if not _dfh.empty and "DataEvento" in _dfh.columns:
                _dias_h = sorted(set(
                    d for d in _dfh["DataEvento"].astype(str).str.slice(0, 10).tolist()
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(d)) and str(d) < data_hoje))
                for _dk in reversed(_dias_h[-30:]):
                    _h = _range_do_historico_csv(_dk, ativo)
                    if not _coerente(num(_h.get("maxima", 0)), num(_h.get("minima", 0))):
                        continue
                    # Distancia em dias corridos ate o dia util anterior real.
                    try:
                        _gap = abs((datetime.strptime(_dk, "%Y-%m-%d")
                                    - datetime.strptime(data_ant, "%Y-%m-%d")).days)
                    except Exception:
                        _gap = 99
                    _h["fonte"] = ("pregao_anterior_historico" if _gap <= 3
                                   else f"referencia_antiga_{_gap}d")
                    _h["dias_de_distancia"] = _gap
                    return _h
    except Exception:
        pass

    # 6. Range acumulado de qualquer data ANTERIOR gravada em disco.
    try:
        mapa = _carregar_range_dia()
        ants = [(k.split("::")[-1], v) for k, v in mapa.items()
                if isinstance(v, dict) and "::" in k
                and k.split("::")[-1] < data_hoje
                and (not ativo or k.startswith(ativo[:3]))]
        ants = [t for t in ants if num(t[1].get("maxima", 0)) > num(t[1].get("minima", 0)) > 0]
        if ants:
            _dk, v = sorted(ants, key=lambda t: t[0])[-1]
            _h = _range_do_historico_csv(_dk, ativo)
            return {"maxima": num(v.get("maxima", 0)), "minima": num(v.get("minima", 0)),
                    "ajuste": num(_h.get("ajuste", 0)), "vwap": num(_h.get("vwap", 0)),
                    "data": _dk, "fonte": "pregao_anterior_registrado"}
    except Exception:
        pass

    # 6. Range acumulado do PROPRIO dia. Enquanto o pregao anterior nao existir
    #    no disco, as faixas saem do que ja foi lido hoje — e a garantia de que
    #    a tela nunca fica sem as tres zonas.
    try:
        _rg = st.session_state.get("ultimo_range_dia") or {}
        _mx, _mn = num(_rg.get("maxima", 0)), num(_rg.get("minima", 0))
        if _mx > _mn > 0 and num(_rg.get("amplitude", 0)) >= AMPLITUDE_MINIMA_RANGE:
            return {"maxima": _mx, "minima": _mn,
                    "ajuste": num((st.session_state.get("ultimos_dados_tela") or {}).get("ajuste", 0)),
                    "vwap": num((st.session_state.get("ultimos_dados_tela") or {}).get("vwap", 0)),
                    "data": data_hoje, "fonte": "range_do_dia_corrente"}
    except Exception:
        pass

    return {"maxima": 0.0, "minima": 0.0, "ajuste": 0.0, "vwap": 0.0,
            "data": data_ant, "fonte": "indisponivel"}


def chave_pregao_analisado(dados_tela=None):
    """Identidade do pregao em analise: ativo + data. Troca de replay troca a chave."""
    d = dados_tela or {}
    _at = ativo_canonico(d.get("ativo", "")) or "ATIVO"
    return f"{_at}::{_data_referencia_leitura(d)}"


def invalidar_faixas_travadas():
    """Libera o recalculo das faixas — chamar ao mudar a configuracao do pregao."""
    for _k in ("faixas_travadas", "faixas_travadas_chave"):
        try:
            st.session_state.pop(_k, None)
        except Exception:
            pass


def calcular_faixas_operacionais(fechamento_ant=None, dados_tela=None):
    """Faixas do pregao anterior, CONGELADAS na primeira leitura da sessao.

    Depois de definidas, as zonas nao se movem mais: so mudam quando a
    configuracao de pregao muda (outra data de replay, ou virada de dia).
    """
    _chave_pa = chave_pregao_analisado(dados_tela)
    _trava = st.session_state.get("faixas_travadas")
    if (isinstance(_trava, dict) and _trava.get("valido")
            and st.session_state.get("faixas_travadas_chave") == _chave_pa):
        _saida = dict(_trava)
        # A zona em que o PRECO esta continua acompanhando a leitura; as
        # bordas das faixas e que ficam imoveis.
        _p_now = num((dados_tela or {}).get("preco_atual", 0))
        if _p_now > 0:
            _vd, _am, _vm = _saida.get("verde"), _saida.get("amarela"), _saida.get("vermelha")
            if _vd and _vd[0] <= _p_now <= _vd[1]:
                _saida["faixa_atual"], _saida["acao_permitida"] = "verde", "compra"
            elif _vm and _vm[0] <= _p_now <= _vm[1]:
                _saida["faixa_atual"], _saida["acao_permitida"] = "vermelha", "venda"
            elif _am and _am[0] <= _p_now <= _am[1]:
                _saida["faixa_atual"], _saida["acao_permitida"] = "amarela", ""
            else:
                _saida["faixa_atual"], _saida["acao_permitida"] = "neutra", "ambas"
        _saida["travada"] = True
        return _saida
    _res = _calcular_faixas_operacionais_bruto(fechamento_ant, dados_tela)
    if isinstance(_res, dict) and _res.get("valido"):
        st.session_state["faixas_travadas"] = dict(_res)
        st.session_state["faixas_travadas_chave"] = _chave_pa
    _res["travada"] = False
    return _res


def _calcular_faixas_operacionais_bruto(fechamento_ant=None, dados_tela=None):
    """Monta as faixas de cor a partir da maxima, minima e ajuste de ontem.

    Devolve as bordas de cada zona e em qual delas o preco atual esta, com a
    acao que aquela faixa autoriza.
    """
    fa = fechamento_ant if isinstance(fechamento_ant, dict) else (ler_fechamento_anterior() or {})
    d = dados_tela or {}
    preco = num(d.get("preco_atual", 0))

    # As faixas saem SEMPRE do dia util imediatamente anterior ao pregao
    # analisado — inclusive no replay, onde a data de referencia e a do replay.
    _ref = referencia_pregao_anterior(d)
    maxima = num(_ref.get("maxima", 0))
    minima = num(_ref.get("minima", 0))
    ajuste = num(_ref.get("ajuste", 0))
    vwap_ant = num(_ref.get("vwap", 0))
    _data_ref_ant = str(_ref.get("data", ""))
    _fonte_ref = str(_ref.get("fonte", ""))

    # Fechamento salvo entra apenas como complemento do ajuste/VWAP ausentes.
    if ajuste <= 0:
        ajuste = num(fa.get("ajuste", 0))
    if vwap_ant <= 0:
        vwap_ant = num(fa.get("vwap", 0))
    # Coerencia de escala: referencia de outro contrato (preco muito distante do
    # atual) nao serve de faixa. Em vez de apagar as zonas, TROCA a referencia
    # pelo range do proprio dia — as faixas continuam na tela, so mudam de base.
    if maxima > 0 and preco > 0 and abs(((maxima + minima) / 2.0) - preco) > (preco * 0.04):
        _rg_c = st.session_state.get("ultimo_range_dia") or {}
        _mxc, _mnc = num(_rg_c.get("maxima", 0)), num(_rg_c.get("minima", 0))
        if _mxc > _mnc > 0 and num(_rg_c.get("amplitude", 0)) >= AMPLITUDE_MINIMA_RANGE:
            maxima, minima = _mxc, _mnc
            _data_ref_ant = _data_referencia_leitura(d)
            _fonte_ref = "range_do_dia_corrente (escala trocada)"
        else:
            # Sem range do dia, deriva do proprio candle lido: a amplitude e
            # pequena, mas ainda entrega as tres zonas em torno do preco.
            _mxt, _mnt = num(d.get("maxima", 0)), num(d.get("minima", 0))
            if _mxt > _mnt > 0:
                _meio = (_mxt + _mnt) / 2.0
                _amp_min = max(AMPLITUDE_MINIMA_RANGE * 4, _mxt - _mnt)
                maxima, minima = _meio + _amp_min / 2.0, _meio - _amp_min / 2.0
                _fonte_ref = "estimada_pela_leitura_atual"
            else:
                maxima = minima = 0.0
                _fonte_ref = "descartada_escala_incompativel"

    vazio = {"valido": False, "faixa_atual": "indefinida", "acao_permitida": "",
             "verde": (0.0, 0.0), "amarela": (0.0, 0.0), "vermelha": (0.0, 0.0),
             "amplitude_ant": 0.0,
             "resumo": "Faixas indisponíveis — sem registro do pregão anterior.",
             "distancia_faixa": 0.0, "data_referencia": _data_ref_ant,
             "fonte_referencia": _fonte_ref, "ajuste_ant": 0.0,
             "maxima_ant": 0.0, "minima_ant": 0.0}
    if not (maxima > minima > 0):
        return vazio

    amp = maxima - minima
    # =================================================================
    # LIMIARES ESTRITAMENTE SEQUENCIAIS
    # Invariante garantida por construcao:
    #   minima <= verde_ini < verde_fim < amarela_ini <= amarela_fim
    #           < vermelha_ini < vermelha_fim <= maxima
    # Nenhuma zona sai do range da referencia e nenhuma invade a vizinha.
    # =================================================================
    _fr_ext = min(max(0.05, FRACAO_FAIXA_EXTREMA), 0.28)
    _fr_neu = min(max(0.05, FRACAO_FAIXA_NEUTRA), 0.24)
    esp_ext = amp * _fr_ext
    esp_neu = amp * _fr_neu
    # Folga obrigatoria entre zonas: impede encostar e impede sobrepor.
    _folga = max(amp * 0.04, 0.5)

    # As tres espessuras somadas nunca consomem o range inteiro.
    _disp = amp - 2.0 * _folga
    _soma_esp = 2.0 * esp_ext + esp_neu
    if _disp > 0 and _soma_esp > _disp:
        _k = max(0.15, _disp / _soma_esp)
        esp_ext *= _k
        esp_neu *= _k

    # VERDE (compra): ancorada NA minima, crescendo para DENTRO do range.
    _v_ini, _v_fim = minima, minima + esp_ext
    # VERMELHA (venda): ancorada NA maxima, crescendo para DENTRO do range.
    _m_ini, _m_fim = maxima - esp_ext, maxima

    # AMARELA (neutra): centrada no ajuste/VWAP, obrigada a caber ESTRITAMENTE
    # entre o fim da verde e o inicio da vermelha, com folga nas duas pontas.
    _lim_inf = _v_fim + _folga
    _lim_sup = _m_ini - _folga
    if _lim_sup <= _lim_inf:
        _meio_r = (_v_fim + _m_ini) / 2.0
        _lim_inf = _lim_sup = _meio_r
    if ajuste > 0 and _lim_inf <= ajuste <= _lim_sup:
        centro = ajuste
    elif vwap_ant > 0 and _lim_inf <= vwap_ant <= _lim_sup:
        centro = vwap_ant
    else:
        centro = (_lim_inf + _lim_sup) / 2.0
    _meia = min(esp_neu / 2.0, max(0.0, (_lim_sup - _lim_inf) / 2.0))
    _a_ini = max(_lim_inf, centro - _meia)
    _a_fim = min(_lim_sup, centro + _meia)
    if _a_fim < _a_ini:
        _a_ini = _a_fim = (_lim_inf + _lim_sup) / 2.0

    verde = (round(_v_ini, 2), round(_v_fim, 2))
    amarela = (round(_a_ini, 2), round(_a_fim, 2))
    vermelha = (round(_m_ini, 2), round(_m_fim, 2))

    def _ordenado(vd, am, vm):
        return (minima - 0.01 <= vd[0] <= vd[1] < am[0] <= am[1] < vm[0] <= vm[1]
                <= maxima + 0.01)

    # Rede de seguranca: se o arredondamento quebrou a ordem, reparte o range
    # em tercos — continua sequencial e dentro dos limites da referencia.
    if not _ordenado(verde, amarela, vermelha):
        _t = amp / 3.0
        verde = (round(minima, 2), round(minima + _t * 0.75, 2))
        amarela = (round(minima + _t * 1.05, 2), round(minima + _t * 1.95, 2))
        vermelha = (round(maxima - _t * 0.75, 2), round(maxima, 2))
    _faixas_ordenadas = _ordenado(verde, amarela, vermelha)

    faixa, acao, resumo = "neutra", "", ""
    dist = 0.0
    if preco > 0:
        if verde[0] <= preco <= verde[1]:
            faixa, acao = "verde", "compra"
            resumo = f"Preço na FAIXA VERDE ({verde[0]:.2f}–{verde[1]:.2f}) — zona de compra."
            dist = round(preco - verde[0], 2)
        elif vermelha[0] <= preco <= vermelha[1]:
            faixa, acao = "vermelha", "venda"
            resumo = f"Preço na FAIXA VERMELHA ({vermelha[0]:.2f}–{vermelha[1]:.2f}) — zona de venda."
            dist = round(vermelha[1] - preco, 2)
        elif amarela[0] <= preco <= amarela[1]:
            faixa, acao = "amarela", ""
            resumo = f"Preço na FAIXA AMARELA ({amarela[0]:.2f}–{amarela[1]:.2f}) — aguardar definição."
        else:
            faixa, acao = "neutra", "ambas"
            resumo = f"Preço fora das faixas de referência ({preco:.2f}) — operar pelo setup."
            dist = round(min(abs(preco - verde[1]), abs(preco - vermelha[0])), 2)

    return {"valido": True, "faixa_atual": faixa, "acao_permitida": acao,
            "verde": verde, "amarela": amarela, "vermelha": vermelha,
            "data_referencia": _data_ref_ant, "fonte_referencia": _fonte_ref,
            "ordenadas": bool(_faixas_ordenadas),
            "maxima_ant": round(maxima, 2), "minima_ant": round(minima, 2),
            "ajuste_ant": round(ajuste, 2), "vwap_ant": round(vwap_ant, 2),
            "amplitude_ant": round(amp, 2), "resumo": resumo, "distancia_faixa": dist}


def ler_fechamento_anterior():
    try:
        with open(FECHAMENTO_JSON, "r", encoding="utf-8") as f:
            dados = json.load(f)
        data_fech = dados.get("data", "")
        hoje = datetime.now().strftime("%Y-%m-%d")
        ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        anteontem = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        if data_fech in [ontem, anteontem, hoje]:
            return dados
    except Exception: pass
    return {"data": "", "preco": 0, "ajuste": 0, "vwap": 0, "dxy": 0, "ewz": 0, "vix": 0, "vies": "indefinido"}


def score_minimo_ajustado(estrategia, acao, vies_anterior):
    base = ESTRATEGIAS[estrategia]["score_minimo_base"]
    # AJUSTE: Se a estratégia for Agressividade Média ou Alta, 
    # reduzimos a exigência de score base em 1 ponto para facilitar o gatilho
    if estrategia in ["Agressividade Média", "Agressividade Alta"]:
        base = max(1, base - 1)
        
    if acao == "compra":
        if vies_anterior == "comprador": return max(1, base - 1)
        if vies_anterior == "vendedor": return min(7, base + 1)
    elif acao == "venda":
        if vies_anterior == "vendedor": return max(1, base - 1)
        if vies_anterior == "comprador": return min(7, base + 1)
    return base

# =========================
# MACRO / PTAX
# =========================
def buscar_rss(url, limite=5):
    noticias = []
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item")[:limite]:
            t = item.findtext("title", default="")
            if t: noticias.append(t)
    except Exception: pass
    return noticias


def buscar_noticias_automaticas():
    noticias = []
    for t in buscar_rss("https://br.investing.com/rss/news_285.rss", 6):
        if t not in noticias: noticias.append(t)
    if not noticias: return "Noticias automaticas indisponiveis."
    return "\n".join([f"{i}. {n}" for i, n in enumerate(noticias[:8], 1)])


def buscar_ptax_bacen():
    try:
        hoje = datetime.now().strftime("%m-%d-%Y")
        url = (f"https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
               f"CotacaoDolarDia(dataCotacao=@dataCotacao)?@dataCotacao='{hoje}'"
               f"&$top=1&$format=json&$select=cotacaoVenda")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        valor = resp.json().get("value", [{}])[0].get("cotacaoVenda")
        if valor: return round(float(valor), 4)
    except Exception: pass
    return "N/A"


def obter_ultimo_preco(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            serie = hist["Close"].dropna()
            if not serie.empty: return round(float(serie.iloc[-1]), 2)
    except Exception: pass
    return "N/A"


def _cache_macro_ler():
    try:
        if os.path.exists(ARQ_CACHE_MACRO_WEB):
            with open(ARQ_CACHE_MACRO_WEB, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _cache_macro_gravar(cache):
    try:
        with open(ARQ_CACHE_MACRO_WEB, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _cache_macro_get(chave, ttl=None):
    """Valor em cache ainda dentro da validade, ou None."""
    cache = _cache_macro_ler()
    item = cache.get(chave)
    if not isinstance(item, dict):
        return None
    ttl = ttl if ttl is not None else TTL_CACHE_MACRO.get(chave, 900)
    try:
        ts = datetime.strptime(item.get("ts", ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    if (datetime.now() - ts).total_seconds() > ttl:
        return None
    return item


def _cache_macro_set(chave, valor, fonte, extra=None):
    cache = _cache_macro_ler()
    item = {"valor": valor, "fonte": fonte,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if isinstance(extra, dict):
        item.update(extra)
    cache[chave] = item
    _cache_macro_gravar(cache)
    return item


def _http_json(url, timeout=None):
    """GET JSON puro. Nao depende de tela: e chamada HTTP direta."""
    try:
        r = requests.get(url, timeout=timeout or TIMEOUT_HTTP_MACRO,
                         headers={"User-Agent": "Mozilla/5.0 (AutoPro macro collector)"})
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _http_texto(url, timeout=None):
    try:
        r = requests.get(url, timeout=timeout or TIMEOUT_HTTP_MACRO,
                         headers={"User-Agent": "Mozilla/5.0 (AutoPro macro collector)"})
        r.raise_for_status()
        return r.text
    except Exception:
        return ""


# ---------------------------------------------------------------- BCB / SGS
def bcb_serie_ultimo(serie, n=1):
    """Ultimo valor de uma serie do SGS do Banco Central. Sem chave de API."""
    url = URLS_FONTES_MACRO["bcb_sgs"].format(serie=int(serie), n=int(n))
    dados = _http_json(url)
    if not isinstance(dados, list) or not dados:
        return None
    ult = dados[-1]
    v = num(str(ult.get("valor", "")).replace(",", "."))
    return {"valor": v, "data": str(ult.get("data", ""))} if v else None


def bcb_serie_na_data(serie, data_ref):
    """Valor da serie SGS na data do replay (dd/mm/aaaa)."""
    try:
        d = datetime.strptime(str(data_ref)[:10], "%Y-%m-%d")
    except Exception:
        return None
    ini = (d - timedelta(days=12)).strftime("%d/%m/%Y")
    fim = d.strftime("%d/%m/%Y")
    url = URLS_FONTES_MACRO["bcb_sgs_periodo"].format(serie=int(serie), ini=ini, fim=fim)
    dados = _http_json(url)
    if not isinstance(dados, list) or not dados:
        return None
    ult = dados[-1]
    v = num(str(ult.get("valor", "")).replace(",", "."))
    return {"valor": v, "data": str(ult.get("data", ""))} if v else None


def bcb_ptax(data_ref=None):
    """PTAX de venda. Com data_ref busca o valor daquele dia (replay)."""
    if data_ref:
        try:
            d = datetime.strptime(str(data_ref)[:10], "%Y-%m-%d")
        except Exception:
            d = datetime.now()
    else:
        d = datetime.now()
    for _ in range(6):   # anda para tras em fim de semana e feriado
        url = URLS_FONTES_MACRO["bcb_ptax_dia"].format(data=d.strftime("%m-%d-%Y"))
        dados = _http_json(url)
        val = (dados or {}).get("value") or []
        if val:
            v = num(val[0].get("cotacaoVenda"))
            if v:
                return {"valor": round(v, 4), "data": d.strftime("%Y-%m-%d"),
                        "fonte": "BCB/PTAX"}
        d = d - timedelta(days=1)
    s = bcb_serie_ultimo(BCB_SERIES["PTAX_VENDA"], 1)
    if s:
        s["fonte"] = "BCB/SGS"
        return s
    return None


# ---------------------------------------------------------------- FRED
def fred_ultimo(serie, data_ref=None):
    """Ultima observacao de uma serie do FRED. Requer FRED_API_KEY."""
    if not FRED_API_KEY:
        return None
    url = URLS_FONTES_MACRO["fred_obs"].format(serie=serie, key=FRED_API_KEY, n=40)
    dados = _http_json(url)
    obs = (dados or {}).get("observations") or []
    limite = str(data_ref)[:10] if data_ref else None
    for o in obs:            # vem em ordem decrescente
        d = str(o.get("date", ""))
        if limite and d > limite:
            continue
        v = num(o.get("value"))
        if v:
            return {"valor": v, "data": d, "fonte": "FRED"}
    return None


# ---------------------------------------------------------------- FMP
def fmp_cotacao(ticker, data_ref=None):
    """Cotacao via Financial Modeling Prep. Com data_ref usa o historico."""
    if not FMP_API_KEY:
        return None
    if data_ref:
        try:
            d = datetime.strptime(str(data_ref)[:10], "%Y-%m-%d")
        except Exception:
            d = datetime.now()
        url = URLS_FONTES_MACRO["fmp_hist"].format(
            ticker=ticker, ini=(d - timedelta(days=10)).strftime("%Y-%m-%d"),
            fim=d.strftime("%Y-%m-%d"), key=FMP_API_KEY)
        dados = _http_json(url)
        hist = (dados or {}).get("historical") or []
        if hist:
            h = hist[0]
            v = num(h.get("close"))
            if v:
                return {"valor": v, "data": str(h.get("date", "")), "fonte": "FMP"}
        return None
    # Tenta o endpoint /stable primeiro; cai para /api/v3 se nao responder.
    dados = _http_json(URLS_FONTES_MACRO["fmp_stable_quote"].format(
        ticker=ticker, key=FMP_API_KEY))
    if not (isinstance(dados, list) and dados):
        dados = _http_json(URLS_FONTES_MACRO["fmp_quote"].format(
            ticker=ticker, key=FMP_API_KEY))
    if isinstance(dados, list) and dados:
        v = num(dados[0].get("price"))
        ant = num(dados[0].get("previousClose"))
        if v:
            return {"valor": v, "anterior": ant, "fonte": "FMP",
                    "data": datetime.now().strftime("%Y-%m-%d")}
    return None


def fmp_calendario_economico(dias=1):
    """Agenda economica com valor esperado x divulgado."""
    if not FMP_API_KEY:
        return []
    hoje = datetime.now()
    url = URLS_FONTES_MACRO["fmp_calendario"].format(
        ini=hoje.strftime("%Y-%m-%d"),
        fim=(hoje + timedelta(days=int(dias))).strftime("%Y-%m-%d"),
        key=FMP_API_KEY)
    dados = _http_json(url)
    return dados if isinstance(dados, list) else []


# ---------------------------------------------------------- TRADING ECONOMICS
def tradingeconomics_indicador(slug):
    """Le o valor publicado na pagina do indicador (raspagem leve do HTML)."""
    html = _http_texto(URLS_FONTES_MACRO["te_indicador"].format(slug=slug))
    if not html:
        return None
    m = re.search(r'id="ctl00_ContentPlaceHolder1_ctl0\d_LastValue">([\d.,-]+)<', html)
    if not m:
        m = re.search(r'<td[^>]*class="[^"]*te-value[^"]*"[^>]*>\s*([\d.,-]+)\s*<', html)
    if not m:
        return None
    v = num(m.group(1).replace(",", "."))
    return {"valor": v, "fonte": "TradingEconomics",
            "data": datetime.now().strftime("%Y-%m-%d")} if v else None


# ---------------------------------------------------------------- INVESTING
def investing_indice(slug):
    """Le a cotacao na pagina do Investing.com (raspagem leve)."""
    html = _http_texto(URLS_FONTES_MACRO["investing_indice"].format(slug=slug))
    if not html:
        return None
    m = re.search(r'data-test="instrument-price-last"[^>]*>([\d.,]+)<', html)
    if not m:
        m = re.search(r'id="last_last"[^>]*>([\d.,]+)<', html)
    if not m:
        return None
    bruto = m.group(1)
    v = num(bruto.replace(".", "").replace(",", ".")) if "," in bruto else num(bruto)
    return {"valor": v, "fonte": "Investing",
            "data": datetime.now().strftime("%Y-%m-%d")} if v else None


# =============================================================================
# COLETA COM CADEIA DE FONTES
# =============================================================================
def coletar_indicador_web(nome, data_ref=None, usar_cache=True):
    """Busca UM indicador percorrendo a cadeia de fontes ate obter valor.

    nome: 'PTAX' | 'DXY' | 'VIX' | 'EWZ' | 'PMI'
    data_ref: data do replay (aaaa-mm-dd). Fontes com historico (BCB, FRED, FMP)
              devolvem o valor daquela data; as de raspagem nao tem historico e
              sao ignoradas no replay para nao contaminar a leitura.
    """
    chave = f"{nome}@{str(data_ref)[:10]}" if data_ref else nome
    if usar_cache and not data_ref:
        c = _cache_macro_get(nome)
        if c:
            return {"valor": c.get("valor"), "fonte": c.get("fonte"),
                    "data": c.get("data", ""), "cache": True,
                    "anterior": c.get("anterior")}

    historicas = ("bcb", "fred", "fmp")
    for fonte in FONTES_MACRO_WEB.get(nome, []):
        if data_ref and fonte not in historicas:
            continue          # raspagem nao serve para data passada
        r = None
        try:
            if fonte == "bcb" and nome == "PTAX":
                r = bcb_ptax(data_ref)
            elif fonte == "fred":
                serie = FRED_SERIES.get("DXY" if nome == "DXY" else
                                        "VIX" if nome == "VIX" else
                                        "PMI_SENTIMENTO" if nome == "PMI" else "")
                r = fred_ultimo(serie, data_ref) if serie else None
            elif fonte == "fmp":
                ticker = {"DXY": "^DXY", "VIX": "^VIX", "EWZ": "EWZ",
                          "PTAX": "USDBRL"}.get(nome)
                r = fmp_cotacao(ticker, data_ref) if ticker else None
            elif fonte == "tradingeconomics":
                # 'manufacturing-pmi' e a pagina do PMI; business-confidence
                # devolvia outro indicador e nunca casava com o campo PMI.
                slug = {"PMI": "manufacturing-pmi", "DXY": "currency"}.get(nome)
                r = tradingeconomics_indicador(slug) if slug else None
                if r is None and nome == "PMI":
                    r = tradingeconomics_indicador("services-pmi")
            elif fonte == "investing":
                slug = {"DXY": "usdollar", "VIX": "volatility-s-p-500",
                        "EWZ": "ishares-msci-brazil-index"}.get(nome)
                r = investing_indice(slug) if slug else None
        except Exception:
            r = None
        if r and r.get("valor"):
            r.setdefault("fonte", fonte)
            if not data_ref:
                _cache_macro_set(nome, r["valor"], r["fonte"],
                                 {"data": r.get("data", ""), "anterior": r.get("anterior")})
            r["cache"] = False
            return r

    if usar_cache:
        c = _cache_macro_get(nome, ttl=86400)   # ultimo valor conhecido do dia
        if c:
            return {"valor": c.get("valor"), "fonte": str(c.get("fonte", "")) + " (cache)",
                    "data": c.get("data", ""), "cache": True,
                    "anterior": c.get("anterior")}
    return {"valor": None, "fonte": "indisponivel", "data": "", "cache": False}


def coletar_macro_web(data_ref=None):
    """Coleta TODOS os indicadores macro por HTTP. Independe de tela aberta."""
    saida = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "data_referencia": str(data_ref)[:10] if data_ref else "",
             "fontes": {}, "indisponiveis": []}
    for nome in ("PTAX", "DXY", "VIX", "EWZ", "PMI"):
        r = coletar_indicador_web(nome, data_ref=data_ref)
        saida[nome] = r.get("valor")
        saida["fontes"][nome] = r.get("fonte", "")
        if r.get("anterior"):
            saida[nome + "_ANTERIOR"] = r.get("anterior")
        if r.get("valor") is None:
            saida["indisponiveis"].append(nome)
    # PMI detalhado do FRED quando houver chave
    for chave, serie in (("PMI_ISM", FRED_SERIES.get("PMI_ISM_MANUFATURA")),
                         ("PMI_SENTIMENTO", FRED_SERIES.get("PMI_SENTIMENTO"))):
        if serie:
            r = fred_ultimo(serie, data_ref)
            if r:
                saida[chave] = r["valor"]
    # Disponibilidade do macro NAO depende do PMI. Com DXY, VIX, EWZ e PTAX
    # presentes ja e possivel calcular vies; exigir o PMI mensal deixava o
    # macro neutro em 100% das leituras.
    ESSENCIAIS_MACRO = ("DXY", "VIX", "EWZ", "PTAX")
    _faltam_essenciais = [k for k in ESSENCIAIS_MACRO if saida.get(k) is None]
    saida["indisponiveis_essenciais"] = _faltam_essenciais
    saida["completo"] = not _faltam_essenciais
    saida["parcial"] = bool(saida["indisponiveis"]) and not _faltam_essenciais
    return saida


def coletar_dados_macro():
    tickers = {
        "DXY": ["DX-Y.NYB", "USDBRL=X"], "EWZ": ["EWZ"],
        "USDBRL": ["USDBRL=X"], "SPY": ["SPY"], "QQQ": ["QQQ"],
        "VIX": ["^VIX"], "TLT": ["TLT"], "GLD": ["GLD"], "CL_OIL": ["CL=F"],
    }
    dados = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "noticias": buscar_noticias_automaticas(),
        "PTAX": buscar_ptax_bacen(),
    }
    # Coleta web por HTTP: roda sem nenhuma tela aberta e tem prioridade sobre
    # o valor lido de cotacao, porque vem da fonte oficial.
    try:
        _web = coletar_macro_web()
        for _k in ("PTAX", "DXY", "VIX", "EWZ", "PMI", "PMI_ISM"):
            if _web.get(_k) is not None:
                dados[_k] = _web[_k]
            if _web.get(_k + "_ANTERIOR") is not None:
                dados[_k + "_ANTERIOR"] = _web[_k + "_ANTERIOR"]
        dados["macro_fontes"] = _web.get("fontes", {})
        dados["macro_indisponiveis"] = _web.get("indisponiveis", [])
        dados["macro_indisponiveis_essenciais"] = _web.get("indisponiveis_essenciais", [])
        dados["macro_completo"] = bool(_web.get("completo"))
        # Guarda a leitura ANTERIOR de DXY e EWZ. Sem ela a variacao percentual
        # nunca era calculada e o macro ficava neutro em 100% das linhas.
        _prev = _ler_macro_arquivo() or {}
        for _k in ("DXY", "EWZ", "VIX"):
            _novo, _velho = num(_web.get(_k)), num(_prev.get(_k))
            if _novo > 0 and _velho > 0 and abs(_novo - _velho) > 1e-9:
                dados[_k + "_ANTERIOR"] = _velho
            elif num(_prev.get(_k + "_ANTERIOR")) > 0:
                dados[_k + "_ANTERIOR"] = num(_prev.get(_k + "_ANTERIOR"))
    except Exception:
        dados["macro_indisponiveis"] = ["coleta_web_falhou"]
        dados["macro_completo"] = False
    for nome, candidatos in tickers.items():
        v = "N/A"
        for t in candidatos:
            v = obter_ultimo_preco(t)
            if v != "N/A": break
        dados[nome] = v
    try:
        with open(MACRO_JSON, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception: pass
    return dados


def ler_dados_macro():
    """Le o macro salvo e mescla os valores de PMI informados na interface."""
    _base = _ler_macro_arquivo()
    try:
        for _k, _s in (("PMI_ISM_SERVICOS", "pmi_ism_servicos"),
                       ("PMI_SP_SERVICOS", "pmi_sp_servicos"),
                       ("PMI_MANUFATURA", "pmi_manufatura"),
                       ("PMI_COMPOSTO", "pmi_composto")):
            _v = float(st.session_state.get(_s, 0) or 0)
            if _v > 0:
                _base[_k] = _v
    except Exception:
        pass
    return _base


def _ler_macro_arquivo():
    try:
        with open(MACRO_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {k: "N/A" for k in ["DXY","EWZ","USDBRL","PTAX","SPY","QQQ","VIX","TLT","GLD","CL_OIL","noticias","timestamp"]}


# =========================
# CAPTURA DE JANELA
# =========================
# Padroes sonoros por tipo de evento (frequencia Hz, duracao ms)
PADROES_SONOROS = {
    "gatilho_compra":  [(880, 150), (1180, 150), (1480, 300)],   # escala ascendente
    "gatilho_venda":   [(1480, 150), (1180, 150), (880, 300)],   # escala descendente
    "reversao":        [(1600, 120), (900, 120), (1600, 120), (900, 300)],  # sirene dupla
    "alerta_maximo":   [(2000, 100), (1500, 100), (2000, 100), (1500, 100), (2000, 400)],
    "aviso":           [(1000, 500)],
}


def disparar_alarme(texto, tipo="aviso", falar=True):
    """Dispara alerta sonoro com padrao especifico + voz opcional.
    tipo: gatilho_compra | gatilho_venda | reversao | alerta_maximo | aviso"""
    if not st.session_state.get("som_ativo", True):
        return

    # Voz em thread separada (nao trava a interface)
    if falar and texto:
        texto = texto_para_voz(texto)
        def _w():
            try:
                pythoncom.CoInitialize()
                win32com.client.Dispatch("SAPI.SpVoice").Speak(texto)
                pythoncom.CoUninitialize()
            except Exception:
                pass
        threading.Thread(target=_w, daemon=True).start()

    # Sequencia de bipes em thread separada
    texto = texto_para_voz(texto) if texto else texto
    seq = PADROES_SONOROS.get(tipo, PADROES_SONOROS["aviso"])
    def _beeps():
        try:
            for freq, dur in seq:
                winsound.Beep(freq, dur)
        except Exception:
            pass
    threading.Thread(target=_beeps, daemon=True).start()

    # Registra no historico de alertas da sessao
    try:
        hist = st.session_state.get("historico_alertas", [])
        hist.insert(0, {
            "hora": datetime.now().strftime("%H:%M:%S"),
            "tipo": tipo,
            "texto": texto,
        })
        st.session_state["historico_alertas"] = hist[:20]
    except Exception:
        pass


def consolidar_veredito(contexto, mudanca_desc="", mudanca_ativa=False):
    """Funde as cinco leituras numa indicacao unica.

    Fontes independentes:
      1. Gatilho    — decisao do motor (ARMADO / ESPERA / BLOQUEADO)
      2. Previsao   — projecao de 5 e 10 min
      3. Book/fluxo — absorcao, desequilibrio e grandes lotes
      4. Setups     — reversao no extremo, pullback (os de maior acerto medido)
      5. Mudanca brusca — inversao recente de regime ou direcao

    Devolve direcao, quantas fontes concordam e o nivel de convicao.
    """
    ctx = contexto or {}
    votos = {"compra": 0.0, "venda": 0.0}
    detalhe = []

    # --- 1) Gatilho do motor (peso 3: e a decisao ja filtrada) ---
    # Antes lia sempre "ultimo_status_gatilho", que so e gravado no FIM do ciclo:
    # o veredito pesava o gatilho da leitura ANTERIOR. Agora prefere o sg atual.
    _sg = str(ctx.get("_sg_atual") or st.session_state.get("ultimo_status_gatilho", ""))
    _acao = str(ctx.get("acao_objetiva", "espera"))
    if _acao in ("compra", "venda"):
        _p = 3.0 if _sg == "ARMADO" else 1.0
        votos[_acao] += _p
        detalhe.append(f"Gatilho {_sg.lower() or 'pendente'}: {_acao}")

    # --- 2) Previsao (peso 2, so a partir de 35% de conviccao) ---
    _pd = str(ctx.get("previsao_direcao", "indefinido"))
    _pc = int(num(ctx.get("previsao_confianca", 0)))
    if _pd in ("compra", "venda") and _pc >= 35:
        votos[_pd] += 2.0
        detalhe.append(f"Previsão {_pd} ({_pc}%)")

    # --- 3) Book e fluxo (peso 3: absorcao e o melhor indicador medido) ---
    _abs = str(ctx.get("fluxo_absorcao", ""))
    if _abs == "compra_absorvendo_venda":
        votos["compra"] += 3.0; detalhe.append("Absorção compradora no fluxo")
    elif _abs == "venda_absorvendo_compra":
        votos["venda"] += 3.0; detalhe.append("Absorção vendedora no fluxo")

    _des = num(ctx.get("fluxo_desequilibrio", 0))
    if abs(_des) >= 20:
        _lado = "compra" if _des > 0 else "venda"
        votos[_lado] += 1.0
        detalhe.append(f"Book desequilibrado para {_lado} ({_des:+.0f}%)")

    _lv = str(ctx.get("lotes_vies", ""))
    _lf = int(num(ctx.get("lotes_forca", 0)))
    if _lv in ("compra", "venda") and _lf >= 30:
        votos[_lv] += 1.5
        detalhe.append(f"Grandes lotes sustentando {_lv} (força {_lf})")

    # --- 4) Setups de maior acerto medido (peso 3) ---
    if ctx.get("reversao_extremo") and _acao in ("compra", "venda"):
        votos[_acao] += 3.0
        detalhe.append(f"Reversão no extremo do range")
    if ctx.get("pullback_favoravel") and _acao in ("compra", "venda"):
        votos[_acao] += 3.0
        detalhe.append("Pullback a favor da tendência")

    # --- 5) Mudanca brusca (peso 2) — agora VOLTA para a decisao ---
    _d = str(mudanca_desc or "")
    if mudanca_ativa and _d:
        if "para compra" in _d or "trend_up" in _d or "de alta" in _d:
            votos["compra"] += 2.0; detalhe.append("Mudança brusca para compra")
        elif "para venda" in _d or "trend_down" in _d or "de queda" in _d:
            votos["venda"] += 2.0; detalhe.append("Mudança brusca para venda")

    # --- Contra-indicadores medidos (subtraem) ---
    contras = []
    if ctx.get("momentum_forte_penalizado"):
        contras.append("momentum esticado (42% de acerto)")
    if str(ctx.get("rompimento_direcao", "")) in ("compra", "venda") and ctx.get("rompimento_dispara"):
        contras.append("rompimento isolado (39% de acerto)")
    if ctx.get("score_saturado"):
        contras.append("score saturado")
    if ctx.get("entrada_tardia"):
        contras.append("preço esticado da MM9")

    _tot = votos["compra"] + votos["venda"]
    if _tot <= 0:
        return {"direcao": "indefinida", "convicao": 0, "fontes": 0,
                "detalhe": [], "contras": contras, "acao_sugerida": "aguardar",
                "resumo": "Sem fonte apontando direção — aguardar."}

    _dir = "compra" if votos["compra"] > votos["venda"] else "venda"
    _dom = max(votos["compra"], votos["venda"])
    _convicao = int(min(100, round((_dom / max(6.0, _tot)) * 100)))
    if votos["compra"] > 0 and votos["venda"] > 0:
        _convicao = int(_convicao * (1 - min(0.5, min(votos.values()) / _dom)))
    _convicao = max(0, _convicao - len(contras) * 12)
    _fontes = len(detalhe)

    if _sg == "ARMADO" and _convicao >= 55:
        _sugerida = f"executar {_dir}"
    elif _convicao >= 55:
        _sugerida = f"preparar {_dir}"
    elif _convicao >= 30:
        _sugerida = f"monitorar {_dir}"
    else:
        _sugerida = "aguardar"

    _txt_contra = f" · contra: {', '.join(contras)}" if contras else ""
    return {"direcao": _dir, "convicao": _convicao, "fontes": _fontes,
            "detalhe": detalhe[:6], "contras": contras, "acao_sugerida": _sugerida,
            "resumo": (f"{_fontes} leituras apontam {_dir} · convicção {_convicao}%{_txt_contra}")}


def regime_em_palavras(regime):
    """Traduz o nome tecnico do regime para linguagem falada."""
    r = str(regime or "").lower()
    mapa = {
        "trend_up": "tendência de compra",
        "trend_down": "tendência de venda",
        "pullback_up": "correção dentro de tendência de compra",
        "pullback_down": "correção dentro de tendência de venda",
        "range": "mercado lateral",
        "misto": "mercado sem definição",
        "inconsistente": "leitura inconsistente",
    }
    return mapa.get(r, r.replace("_", " "))


def texto_para_voz(txt):
    """Remove jargao tecnico da fala do alerta."""
    t = str(txt or "")
    for k, v in (
        ("trend_up", "tendência de compra"),
        ("trend_down", "tendência de venda"),
        ("pullback_up", "correção em tendência de compra"),
        ("pullback_down", "correção em tendência de venda"),
        ("Regime virou de", "Mercado mudou de"),
        ("Direcao inverteu de compra para venda", "direção inverteu para venda"),
        ("Direcao inverteu de venda para compra", "direção inverteu para compra"),
        ("compra", "compra"), ("venda", "venda"),
        ("_", " "), ("|", "."),
    ):
        t = t.replace(k, v)
    return t


def referencias_proximas_abertura(preco, dados_tela, fechamento_ant=None, tolerancia=4.0):
    """Referencias do dia anterior perto do preco de abertura.

    Abrir colado no pivo, na VWAP, na maxima ou na minima de ontem muda tudo:
    o nivel vira suporte ou resistencia imediata e ja aponta o lado a operar.
    """
    if preco <= 0:
        return []
    _fa = fechamento_ant or {}
    _piv = calcular_pivot_points(
        num(_fa.get("maxima_dia", 0)), num(_fa.get("minima_dia", 0)),
        num(_fa.get("preco", 0)) or num((dados_tela or {}).get("ajuste", 0)),
    )
    cand = [
        (num(_piv.get("pivot", 0)), "Pivô", 3), (num(_piv.get("r1", 0)), "R1", 3),
        (num(_piv.get("s1", 0)), "S1", 3), (num(_piv.get("r2", 0)), "R2", 2),
        (num(_piv.get("s2", 0)), "S2", 2),
        (num(_fa.get("maxima_dia", 0)), "Máxima D-1", 3),
        (num(_fa.get("minima_dia", 0)), "Mínima D-1", 3),
        (num(_fa.get("vwap", 0)), "VWAP D-1", 2),
        (num(_fa.get("preco", 0)), "Fechamento D-1", 2),
        (num((dados_tela or {}).get("ajuste", 0)), "Ajuste", 3),
        (num((dados_tela or {}).get("mm200", 0)), "MM200", 3),
    ]
    out = []
    for v, nome, peso in cand:
        if v <= 0:
            continue
        d = preco - v
        if abs(d) <= tolerancia:
            out.append({"nivel": nome, "preco": round(v, 2), "dist": round(d, 2),
                        "peso": peso, "lado": "acima" if d > 0 else "abaixo"})
    return sorted(out, key=lambda x: abs(x["dist"]))


def avaliar_janela_abertura(dados_tela, fechamento_ant=None):
    """Primeiros minutos do dia: observar, nao operar.

    Retorna o diagnostico da abertura (onde abriu, gap contra o fechamento
    anterior, tendencia que se forma) e se o gatilho deve ficar suspenso.
    """
    r = {"em_observacao": False, "minutos_desde_abertura": 0, "gap_pts": 0.0,
         "tipo_abertura": "", "tendencia_formando": "indefinida", "resumo": "",
         "abertura": 0.0, "fech_anterior": 0.0, "referencias": [],
         "ancora": "", "leitura_antecipada": ""}

    hora = str(dados_tela.get("hora_replay") or dados_tela.get("hora") or "").strip()
    mnt = parse_hm(hora)
    abre = parse_hm(HORA_ABERTURA_MERCADO)
    if mnt <= 0 or abre <= 0:
        return r

    decorridos = mnt - abre
    r["minutos_desde_abertura"] = decorridos
    if decorridos < 0 or decorridos > 360:
        return r

    preco = num(dados_tela.get("preco_atual", 0))
    abertura = num(dados_tela.get("abertura", 0)) or preco
    fech_ant = num((fechamento_ant or {}).get("preco", 0))
    r["abertura"] = abertura
    r["fech_anterior"] = fech_ant

    if fech_ant > 0 and abertura > 0:
        gap = abertura - fech_ant
        r["gap_pts"] = round(gap, 2)
        if gap >= 3.0:
            r["tipo_abertura"] = "gap de alta"
        elif gap <= -3.0:
            r["tipo_abertura"] = "gap de baixa"
        else:
            r["tipo_abertura"] = "abertura sem gap relevante"

    # Referencias do dia anterior coladas na abertura
    refs = referencias_proximas_abertura(preco, dados_tela, fechamento_ant)
    r["referencias"] = refs[:4]
    if refs:
        _r0 = refs[0]
        r["ancora"] = f"{_r0['nivel']} em {_r0['preco']:.2f} ({_r0['dist']:+.1f} pts)"

    # Tendencia que se forma — limiar baixo para decidir ja aos 5 min
    hc = st.session_state.get("hist_candles", [])
    if preco > 0 and abertura > 0:
        avanco = preco - abertura
        if abs(avanco) >= 1.5:
            r["tendencia_formando"] = "compra" if avanco > 0 else "venda"
        elif len(hc) >= 2:
            _c0, _c1 = hc[0], hc[1]
            if num(_c0.get("fechamento", 0)) > num(_c1.get("fechamento", 0)):
                r["tendencia_formando"] = "compra"
            elif num(_c0.get("fechamento", 0)) < num(_c1.get("fechamento", 0)):
                r["tendencia_formando"] = "venda"

    # Leitura antecipada: preco defendendo ou rejeitando uma referencia forte
    if refs and r["tendencia_formando"] in ("compra", "venda"):
        _r0 = refs[0]
        if _r0["peso"] >= 3:
            if _r0["lado"] == "acima" and r["tendencia_formando"] == "compra":
                r["leitura_antecipada"] = f"sustentando {_r0['nivel']} — favorece compra"
            elif _r0["lado"] == "abaixo" and r["tendencia_formando"] == "venda":
                r["leitura_antecipada"] = f"rejeitando {_r0['nivel']} — favorece venda"
            else:
                r["leitura_antecipada"] = f"testando {_r0['nivel']} — aguardar definição"

    r["em_observacao"] = decorridos < MINUTOS_OBSERVACAO_ABERTURA

    if r["em_observacao"]:
        _falta = MINUTOS_OBSERVACAO_ABERTURA - decorridos
        _g = f" · {r['tipo_abertura']} de {abs(r['gap_pts']):.1f} pts" if r["tipo_abertura"] else ""
        _a = f" · próximo de {r['ancora']}" if r["ancora"] else ""
        r["resumo"] = (f"Observando a abertura: abriu em {abertura:.2f}{_g}{_a}. "
                       f"Aguardando {_falta} min para confirmar a tendência.")
    else:
        _t = r["tendencia_formando"]
        _a = f" · ancorado em {r['ancora']}" if r["ancora"] else ""
        _l = f" · {r['leitura_antecipada']}" if r["leitura_antecipada"] else ""
        r["resumo"] = (f"Abertura definida em {abertura:.2f}{_a} · tendência: "
                       f"{'compra' if _t == 'compra' else ('venda' if _t == 'venda' else 'indefinida')}{_l}.")
    return r


def detectar_mudanca_brusca(contexto, dados_tela):
    """Compara o estado atual com a leitura anterior e detecta viradas bruscas.
    Retorna (bool_mudou, descricao, tipo_sonoro)."""
    ant = st.session_state.get("estado_anterior_tendencia", {})
    regime_atual = str(contexto.get("regime", ""))
    vies_atual = str(contexto.get("acao_pretendida", contexto.get("acao_objetiva", "")))
    preco_atual = num(dados_tela.get("preco_atual", 0))
    agr_atual = float(contexto.get("saldo_agressao_pct", 50.0) or 50.0)

    # Salva o estado corrente para a proxima comparacao
    st.session_state["estado_anterior_tendencia"] = {
        "regime": regime_atual, "vies": vies_atual,
        "preco": preco_atual, "agressao": agr_atual,
    }

    if not ant:
        return False, "", ""

    motivos = []
    tipo_som = "reversao"

    # a) Inversao de regime (alta <-> baixa)
    r_ant = str(ant.get("regime", ""))
    if r_ant and regime_atual:
        subiu = "up" in r_ant and "down" in regime_atual
        caiu = "down" in r_ant and "up" in regime_atual
        if subiu or caiu:
            motivos.append(f"Regime virou de {r_ant} para {regime_atual}")

    # b) Inversao da direcao pretendida (compra <-> venda)
    v_ant = str(ant.get("vies", ""))
    _p_ant_chk = num(ant.get("preco", 0))
    _delta_chk = abs(preco_atual - _p_ant_chk) if (_p_ant_chk > 0 and preco_atual > 0) else 0.0
    # Inverter direcao sem o preco ter andado e ruido, nao reversao.
    # Registros com delta 0.0 invertendo compra<->venda poluiam o alerta.
    if (v_ant in ("compra", "venda") and vies_atual in ("compra", "venda")
            and v_ant != vies_atual and _delta_chk >= 1.5):
        motivos.append(f"Direcao inverteu de {v_ant} para {vies_atual}")

    # c) Movimento brusco de preco (>= 8 pontos entre leituras)
    p_ant = num(ant.get("preco", 0))
    if p_ant > 0 and preco_atual > 0:
        delta = preco_atual - p_ant
        if abs(delta) >= 8.0:
            direcao = "alta" if delta > 0 else "queda"
            motivos.append(f"Movimento brusco de {direcao}: {abs(delta):.1f} pontos")
            tipo_som = "alerta_maximo"

    # d) Virada forte no fluxo de agressao (>= 20 pontos percentuais)
    a_ant = float(ant.get("agressao", 50.0) or 50.0)
    if abs(agr_atual - a_ant) >= 20.0:
        lado = "compradora" if agr_atual > a_ant else "vendedora"
        motivos.append(f"Fluxo virou para agressao {lado} ({a_ant:.0f}% para {agr_atual:.0f}%)")
        tipo_som = "alerta_maximo"

    if motivos:
        return True, " | ".join(motivos), tipo_som
    return False, "", ""


def listar_janelas_visiveis():
    return [
        (w.title or "").strip()
        for w in gw.getAllWindows()
        if (w.title or "").strip() and win32gui.IsWindowVisible(w._hWnd)
    ]


def _bitblt_regiao_desktop(min_x, min_y, width, height):
    """Captura direta do desktop via BitBlt na regiao (min_x, min_y, width, height).
    Metodo que FUNCIONA para janelas do Profit (nao depende de PrintWindow por hwnd).
    Funciona em qualquer monitor pois usa coordenadas globais do desktop virtual."""
    try:
        if width <= 10 or height <= 10:
            return None
        hdesktop = win32gui.GetDesktopWindow()
        hdc = win32gui.GetWindowDC(hdesktop)
        mdc = win32ui.CreateDCFromHandle(hdc)
        sdc = mdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mdc, width, height)
        sdc.SelectObject(bmp)
        sdc.BitBlt((0, 0), (width, height), mdc, (min_x, min_y), 0x00CC0020)  # SRCCOPY
        bi = bmp.GetInfo()
        bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (bi["bmWidth"], bi["bmHeight"]), bits, "raw", "BGRX", 0, 1)
        try:
            win32gui.DeleteObject(bmp.GetHandle())
            sdc.DeleteDC(); mdc.DeleteDC(); win32gui.ReleaseDC(hdesktop, hdc)
        except Exception: pass
        return img
    except Exception:
        return None


def _encontrar_janelas_por_palavras(palavras, area_minima=2500):
    """Retorna lista de dicts {titulo, hwnd, l, top, r, b} para todas as janelas
    cujo titulo contem alguma palavra da lista."""
    palavras_low = [p.lower() for p in palavras]
    result = []
    for w in gw.getAllWindows():
        try:
            t = (w.title or "").strip()
            if not t: continue
            if any(p in t.lower() for p in palavras_low):
                l, top, r, b = win32gui.GetWindowRect(w._hWnd)
                if (r - l) * (b - top) < area_minima: continue
                result.append({"titulo": t, "hwnd": w._hWnd, "l": l, "top": top, "r": r, "b": b})
        except Exception: pass
    return result


def _encontrar_janela_palavras(palavras, area_minima=2500):
    """Retorna a MAIOR janela cujo titulo bate com alguma palavra (dict ou None)."""
    lst = _encontrar_janelas_por_palavras(palavras, area_minima)
    if not lst: return None
    lst.sort(key=lambda j: (j["r"] - j["l"]) * (j["b"] - j["top"]), reverse=True)
    j = lst[0]
    return {"titulo": j["titulo"], "hwnd": j["hwnd"], "classe": "", "area": (j["r"]-j["l"])*(j["b"]-j["top"])}


def _enumerar_todas_janelas():
    """Enumera janelas via win32 para diagnostico."""
    janelas = []
    def _cb(hwnd, _):
        try:
            titulo = win32gui.GetWindowText(hwnd) or ""
            classe = win32gui.GetClassName(hwnd) or ""
            l, top, r, b = win32gui.GetWindowRect(hwnd)
            area = max(0, r-l) * max(0, b-top)
            if titulo or area > 50000:
                janelas.append({"hwnd": hwnd, "titulo": titulo, "classe": classe, "area": area})
        except Exception: pass
        return True
    try: win32gui.EnumWindows(_cb, None)
    except Exception: pass
    return janelas


def encontrar_janela_profit():
    palavras = [
        "profit", "nelogica", "proft", "vector", "replay",
        "wdofut", "wdo", "dolar mini", "minuto(s)", "1 dolar"
    ]
    lst = _encontrar_janelas_por_palavras(palavras, area_minima=10000)
    if not lst: return None
    lst.sort(key=lambda j: (j["r"] - j["l"]) * (j["b"] - j["top"]), reverse=True)
    j = lst[0]
    class _Wrapper:
        def __init__(self, hwnd, titulo):
            self._hWnd = hwnd
            self.title = titulo
    return _Wrapper(j["hwnd"], j["titulo"])


def _capturar_por_palavras(palavras, nome_amigavel):
    """Encontra a janela pela lista de palavras e captura sua regiao via BitBlt do desktop.
    Este e o metodo que estava funcionando: nao usa PrintWindow, e sim BitBlt na coordenada
    global — funciona ate em monitor secundario, sem precisar de admin."""
    lst = _encontrar_janelas_por_palavras(palavras, area_minima=2500)
    if not lst:
        return None, f"{nome_amigavel} nao encontrado. Abra a janela no Profit."
    # Pega a MAIOR (evita mini-janelas ou tooltips)
    lst.sort(key=lambda j: (j["r"] - j["l"]) * (j["b"] - j["top"]), reverse=True)
    j = lst[0]
    l, top, w, h = j["l"], j["top"], j["r"] - j["l"], j["b"] - j["top"]
    img = _bitblt_regiao_desktop(l, top, w, h)
    if img is None:
        return None, f"Encontrei '{j['titulo']}' em ({l},{top}) {w}x{h} mas BitBlt falhou."
    return img, f"{nome_amigavel} capturado: '{j['titulo']}' ({w}x{h}px em {l},{top})"


def capturar_tela_completa_profit():
    """Captura a bounding box de TODAS as janelas do Profit num unico screenshot."""
    palavras_profit = [
        "wdofut", "wdo", "dolar mini", "profit", "nelogica",
        "SuperDom", "times && trades", "times & trades", "times",
        "livro de ofertas", "livro", "replay", "boleta", "1 dolar",
        "2 SuperDom", "3 livro", "4 times"
    ]
    janelas_profit = _encontrar_janelas_por_palavras(palavras_profit, area_minima=2500)
    if not janelas_profit:
        return None, "Nenhuma janela do Profit encontrada."
    min_x = min(j["l"] for j in janelas_profit)
    min_y = min(j["top"] for j in janelas_profit)
    max_x = max(j["r"] for j in janelas_profit)
    max_y = max(j["b"] for j in janelas_profit)
    width, height = max_x - min_x, max_y - min_y
    img = _bitblt_regiao_desktop(min_x, min_y, width, height)
    if img is None:
        return None, "BitBlt falhou na regiao completa do Profit."
    titulos = [j["titulo"] for j in janelas_profit]
    return img, f"Captura completa ({width}x{height}px) — {len(janelas_profit)} janelas: {', '.join(titulos[:4])}"


def _capturar_janela_por_hwnd(hwnd, nome_amigavel):
    """
    Captura uma janela específica pelo seu HWND usando PrintWindow,
    funcionando MESMO EM SEGUNDO PLANO ou encoberta por outras janelas.
    """
    try:
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None, f"{nome_amigavel} (HWND inválido)"

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top
        if width <= 10 or height <= 10:
            return None, f"{nome_amigavel} muito pequena ou minimizada."

        # Cria os contextos de dispositivo para captura em background
        hdesktop = win32gui.GetDesktopWindow()
        hdcScreen = win32gui.GetWindowDC(hdesktop)
        hdc = win32ui.CreateDCFromHandle(hdcScreen)
        saveDC = hdc.CreateCompatibleDC()
        
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(hdc, width, height)
        saveDC.SelectObject(saveBitMap)
        
        # Tenta PrintWindow com PW_RENDERFULLCONTENT (0x2) para renderização completa
        result = win32gui.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
        if not result:
            # Fallback para o modo padrão (0)
            result = win32gui.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

        if result:
            bmpinfo = saveBitMap.GetInfo()
            bits = saveBitMap.GetBitmapBits(True)
            img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bits, "raw", "BGRX", 0, 1)
            
            # Limpeza de recursos
            try:
                win32gui.DeleteObject(saveBitMap.GetHandle())
                saveDC.DeleteDC()
                hdc.DeleteDC()
                win32gui.ReleaseDC(hdesktop, hdcScreen)
            except Exception:
                pass

            titulo = win32gui.GetWindowText(hwnd)
            return img, f"{nome_amigavel} capturado em segundo plano: '{titulo}' ({width}x{height}px)"
        else:
            # Se PrintWindow falhar, tenta o BitBlt na coordenada original como último recurso
            img_fallback = _bitblt_regiao_desktop(left, top, width, height)
            if img_fallback is not None:
                return img_fallback, f"{nome_amigavel} capturado via BitBlt (fallback): ({width}x{height}px)"
                
        return None, f"PrintWindow falhou para {nome_amigavel}."
    except Exception as e:
        return None, f"Erro na captura em segundo plano de {nome_amigavel}: {e}"


def _capturar_por_palavras_background(palavras, nome_amigavel):
    """Encontra a janela por palavras-chave e a captura em segundo plano via PrintWindow."""
    lst = _encontrar_janelas_por_palavras(palavras, area_minima=2500)
    if not lst:
        return None, f"{nome_amigavel} não encontrado nas janelas ativas."
    # Pega a maior janela correspondente
    lst.sort(key=lambda j: (j["r"] - j["l"]) * (j["b"] - j["top"]), reverse=True)
    j = lst[0]
    return _capturar_janela_por_hwnd(j["hwnd"], nome_amigavel)


# Adicione esta linha logo após os imports para garantir permissão de DPI no Windows
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


def _capturar_regiao_tela_direta(left, top, width, height):
    """
    Captura pixels diretamente da tela do desktop usando BitBlt de alta performance.
    Ignora restrições de PrintWindow ou aceleração de GPU do Profit.
    """
    try:
        if width <= 10 or height <= 10:
            return None
        hdesktop = win32gui.GetDesktopWindow()
        hdcScreen = win32gui.GetWindowDC(hdesktop)
        hDC = win32ui.CreateDCFromHandle(hdcScreen)
        saveDC = hDC.CreateCompatibleDC()
        
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(hDC, width, height)
        saveDC.SelectObject(bitmap)
        
        # Copia da tela nas coordenadas exatas
        saveDC.BitBlt((0, 0), (width, height), hDC, (left, top), 0x00CC0020) # SRCCOPY
        
        signedints = bitmap.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (width, height), signedints, "raw", "BGRX", 0, 1)
        
        # Limpeza
        win32gui.DeleteObject(bitmap.GetHandle())
        saveDC.DeleteDC()
        hDC.DeleteDC()
        win32gui.ReleaseDC(hdesktop, hdcScreen)
        return img
    except Exception:
        return None


def _imagem_esta_em_branco(img, limiar_variancia=3.0):
    """Detecta captura preta/uniforme: o PrintWindow costuma retornar SUCESSO
    (result != 0) mas devolver um frame preto em janelas com grafico acelerado
    por GPU (caso do grafico do Profit) — por isso o resultado nao pode ser
    validado so pelo codigo de retorno, tem que olhar o conteudo do pixel."""
    try:
        amostra = img.convert("L").resize((64, 64))
        minimo, maximo = amostra.getextrema()
        if maximo - minimo <= 1:
            return True
        media = sum(amostra.getdata()) / (64 * 64)
        variancia = sum((p - media) ** 2 for p in amostra.getdata()) / (64 * 64)
        return variancia < limiar_variancia
    except Exception:
        return False


def _printwindow_regiao(hwnd, w, h, nome_amigavel, titulo_ou_classe):
    """PrintWindow direto no hwnd — unico jeito de capturar uma janela minimizada
    ou totalmente coberta por outra. Usado so como fallback: em janelas com
    grafico acelerado por GPU costuma devolver frame preto (ver _imagem_esta_em_branco)."""
    try:
        hdesktop = win32gui.GetDesktopWindow()
        hdcScreen = win32gui.GetWindowDC(hdesktop)
        hDC = win32ui.CreateDCFromHandle(hdcScreen)
        saveDC = hDC.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(hDC, w, h)
        saveDC.SelectObject(bitmap)

        res = win32gui.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
        if not res:
            res = win32gui.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

        img = None
        if res:
            bits = bitmap.GetBitmapBits(True)
            img = Image.frombuffer("RGB", (w, h), bits, "raw", "BGRX", 0, 1)
        win32gui.DeleteObject(bitmap.GetHandle())
        saveDC.DeleteDC()
        hDC.DeleteDC()
        win32gui.ReleaseDC(hdesktop, hdcScreen)
        if img is not None and not _imagem_esta_em_branco(img):
            return img, f"{nome_amigavel} capturado via PrintWindow (fallback): '{titulo_ou_classe}' ({w}x{h}px)"
    except Exception:
        pass
    return None, None


def _capturar_por_palavras_forcado(palavras, nome_amigavel):
    """
    Busca a janela por palavras-chave em qualquer título ativo do Windows,
    incluindo correspondências parciais e tolerância a abreviações do Profit,
    e captura via BitBlt direto do desktop (o metodo que de fato funciona
    com o grafico do Profit, que e renderizado por GPU). PrintWindow so entra
    como fallback quando a janela esta minimizada/coberta e o BitBlt falha ou
    devolve tela preta — tentar PrintWindow primeiro era o bug: ele "tem
    sucesso" e devolve frame preto no grafico, entao o app nunca caia no
    metodo que funciona.
    """
    palavras_low = [p.lower() for p in palavras]
    candidatos = []

    def _enum_cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            titulo = (win32gui.GetWindowText(hwnd) or "").strip()
            classe = (win32gui.GetClassName(hwnd) or "").strip()
            if not titulo and not classe:
                return True

            t_low = titulo.lower()
            c_low = classe.lower()

            # Verifica se alguma palavra-chave bate com o título ou com a classe
            match = any(p in t_low or p in c_low for p in palavras_low)

            # Se for Times & Trades, Livro ou Agentes, aceita também termos genéricos do Profit se contiverem o ticker

            if match:
                l, top, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - top
                if w > 40 and h > 40: # Ignora janelas minúsculas/tooltips
                    candidatos.append({
                        "hwnd": hwnd, "titulo": titulo, "classe": classe,
                        "l": l, "top": top, "w": w, "h": h, "area": w * h
                    })
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception:
        pass

    if not candidatos:
        return None, f"{nome_amigavel} não encontrado nas janelas ativas."

    # Ordena pela maior área visível
    candidatos.sort(key=lambda x: x["area"], reverse=True)
    melhor = candidatos[0]
    l, top, w, h = melhor["l"], melhor["top"], melhor["w"], melhor["h"]
    titulo_ou_classe = melhor["titulo"] or melhor["classe"]

    # 1) BitBlt direto do desktop: funciona mesmo com o grafico acelerado por GPU,
    # desde que a janela esteja visivel na tela (nao minimizada/nao coberta).
    img_bitblt = _capturar_regiao_tela_direta(l, top, w, h)
    if img_bitblt is not None and not _imagem_esta_em_branco(img_bitblt):
        return img_bitblt, f"{nome_amigavel} capturado: '{titulo_ou_classe}' ({w}x{h}px)"

    # 2) Fallback: PrintWindow (unico jeito de capturar janela minimizada/coberta).
    img_pw, msg_pw = _printwindow_regiao(melhor["hwnd"], w, h, nome_amigavel, titulo_ou_classe)
    if img_pw is not None:
        return img_pw, msg_pw

    # 3) Nenhum metodo deu uma imagem util: devolve o BitBlt mesmo que preto, com
    # aviso, em vez de descartar a leitura por completo.
    if img_bitblt is not None:
        return img_bitblt, (f"{nome_amigavel} capturado, mas a imagem parece em branco/preta: "
                             f"'{titulo_ou_classe}' ({w}x{h}px). Verifique se a janela nao esta "
                             f"minimizada ou coberta por outra.")

    return None, f"Falha total na captura de {nome_amigavel}."

def capturar_janela():
    """Captura o gráfico principal."""
    palavras = ["1 dolar mini", "dolar mini", "wdofut", "wdo", "minuto", "gráfico", "grafico"]
    img, msg = _capturar_por_palavras_forcado(palavras, "Gráfico")
    if img is None:
        # Se falhar pelas palavras específicas, tenta qualquer janela do Profit
        img, msg = _capturar_por_palavras_forcado(["profit", "nelogica"], "Gráfico (Profit Geral)")
    st.session_state.ultimo_titulo_capturado = msg
    return img, msg


def capturar_SuperDom():
    """Captura SuperDOM."""
    palavras = ["superdom", "super dom", "dom", "boleta"]
    img, msg = _capturar_por_palavras_forcado(palavras, "SuperDOM")
    if img is not None:
        st.session_state["ultimo_titulo_superdom"] = msg
    return img, msg


def _janelas_wdofut_ordenadas():
    """Retorna as janelas WDOFUT/DOLPRO/Simulador da esquerda para a direita
    (ordenadas por coordenada X). Assim é possível diferenciar:
    - 1ª (mais à esquerda): T&T na aba Ordem Original
    - 2ª: T&T na aba Negócios
    - 3ª (mais à direita): Book na aba Ofertas / Agentes na aba Negociação"""
    janelas = _encontrar_janelas_por_palavras(
        ["wdofut", "dolpro", "wdo", "dolar", "sim ", "simulador", "216541", "[r] wdofut"],
        area_minima=30000
    )
    # Filtra apenas janelas com altura suficiente (evita a barra do topo)
    janelas = [j for j in janelas if (j["b"] - j["top"]) > 200]
    # Ordena da esquerda para a direita
    return sorted(janelas, key=lambda j: j["l"])


def capturar_times_trades_ordem_original():
    """Captura o Times & Trades na aba ORDEM ORIGINAL (1ª janela da esquerda)."""
    # 1ª tentativa: palavras específicas da aba Ordem Original
    palavras = ["ordem original", "compradora", "vendedora", "agressor", "hora comprad"]
    img, msg = _capturar_por_palavras_forcado(palavras, "T&T Ordem Original")
    if img is not None:
        st.session_state["ultimo_titulo_tt_oo"] = msg
        return img, msg
    # 2ª tentativa: 1ª janela WDOFUT (mais à esquerda) — cenário do seu layout
    janelas = _janelas_wdofut_ordenadas()
    if len(janelas) >= 1:
        j = janelas[0]
        l, top, w, h = j["l"], j["top"], j["r"]-j["l"], j["b"]-j["top"]
        img = _bitblt_regiao_desktop(l, top, w, h)
        if img is not None:
            _msg = f"T&T Ordem Original (1ª janela): '{j['titulo']}' ({w}x{h}px)"
            st.session_state["ultimo_titulo_tt_oo"] = _msg
            return img, _msg
    # 3a tentativa: janela larga do Profit cujo titulo NAO seja do navegador/app.
    # Nunca captura a tela inteira: isso mascarava o erro e quebrava os outros paineis.
    _proibidas = [
        "chrome", "edge", "firefox", "opera", "brave", "navegador",
        "autopro", "streamlit", "localhost", "radar institucional",
        "visual studio", "code", "notepad", "explorador", "explorer",
        "powershell", "prompt", "terminal",
    ]
    _cand = _encontrar_janelas_por_palavras(
        ["wdou", "wdof", "wdo", "dolpro", "dolar", "dólar", "profit", "nelogica", "nelógica"],
        area_minima=150000,
    )
    _cand = [
        j for j in _cand
        if (j["b"] - j["top"]) > 250 and (j["r"] - j["l"]) > 700
        and not any(p in (j["titulo"] or "").lower() for p in _proibidas)
    ]
    if _cand:
        _cand.sort(key=lambda x: (x["r"] - x["l"]) * (x["b"] - x["top"]), reverse=True)
        j = _cand[0]
        l, top, w, h = j["l"], j["top"], j["r"]-j["l"], j["b"]-j["top"]
        img = _bitblt_regiao_desktop(l, top, w, h)
        if img is not None:
            _msg = f"T&T Ordem Original capturado (janela ampla): '{j['titulo']}' ({w}x{h}px)"
            st.session_state["ultimo_titulo_tt_oo"] = _msg
            return img, _msg

    return None, "T&T Ordem Original nao encontrado. Use o botao de diagnostico e me diga os titulos listados."

def capturar_times_trades():
    """Captura Times & Trades. Testa múltiplas palavras-chave e, se falhar,
    tenta pegar a 2ª/3ª maior janela WDOFUT (quando o Profit reusa o título)."""
    palavras = [
        "times", "trades", "t&t", "t & t", "tape", "time", "sales",
        "negocios", "negócios", "negociacao", "negociação",
        "ordem original", "compradora", "vendedora", "agressor",
        "4 times", "5 times", "hora comprad", "book de negoc"
    ]
    img, msg = _capturar_por_palavras_forcado(palavras, "Times & Trades")
    if img is not None:
        st.session_state["ultimo_titulo_tt"] = msg
        return img, msg

    # Fallback: pegar a 2ª maior janela WDOFUT/DOLPRO (as janelas do replay têm o mesmo título)
    janelas_wdo = _encontrar_janelas_por_palavras(
        ["wdofut", "dolpro", "wdo", "dolar", "[r] wdofut"], area_minima=50000
    )
    janelas_wdo = sorted(janelas_wdo, key=lambda j: (j["r"]-j["l"])*(j["b"]-j["top"]), reverse=True)
    if len(janelas_wdo) >= 2:
        # 1ª é o gráfico, 2ª costuma ser o T&T ou Ordem Original
        j = janelas_wdo[1]
        l, top, w, h = j["l"], j["top"], j["r"]-j["l"], j["b"]-j["top"]
        img = _bitblt_regiao_desktop(l, top, w, h)
        if img is not None:
            _msg = f"Times & Trades capturado (fallback 2ª janela WDOFUT): '{j['titulo']}' ({w}x{h}px em {l},{top})"
            st.session_state["ultimo_titulo_tt"] = _msg
            return img, _msg
    return None, f"Times & Trades nao encontrado. Ative a aba Negócios/Ordem Original numa janela separada."


def capturar_livro_ofertas():
    """Captura Livro de Ofertas."""
    palavras = ["livro", "ofertas", "book", "order", "depth", "profundidade"]
    img, msg = _capturar_por_palavras_forcado(palavras, "Livro de Ofertas")
    if img is not None:
        st.session_state["ultimo_titulo_livro"] = msg
    return img, msg


def capturar_todas_janelas_profit(max_janelas=6):
    """Captura TODAS as janelas do Profit de uma vez.

    As abas Ofertas / Negociacao / SuperDOM / Times&Trades ficam DENTRO de
    janelas cujo titulo e apenas o ticker (ex: 'WDOU26', 'WDOU26 1D').
    Buscar por 'Ofertas' no titulo nunca funciona — por isso capturamos todas
    e deixamos a IA identificar o conteudo de cada uma.

    Retorna lista de dicts: {img, titulo, largura, altura, left, top}
    """
    palavras = ["wdou", "wdofut", "wdo", "dolpro", "dolar", "dol",
                "sim ", "simulador", "profit", "nelogica", "replay",
                "216541", "65412", "cross order", "book"]
    janelas = _encontrar_janelas_por_palavras(palavras, area_minima=20000)

    # remove duplicatas por posicao/tamanho
    vistas, unicas = set(), []
    for j in janelas:
        chave = (j["l"], j["top"], j["r"], j["b"])
        if chave in vistas:
            continue
        vistas.add(chave)
        unicas.append(j)

    # prioriza janelas mais largas (paineis de agentes sao largos)
    unicas.sort(key=lambda x: (x["r"] - x["l"]) * (x["b"] - x["top"]), reverse=True)

    resultado = []
    for j in unicas[:max_janelas]:
        l, top = j["l"], j["top"]
        w, h = j["r"] - j["l"], j["b"] - j["top"]
        if w < 200 or h < 120:
            continue
        img = _bitblt_regiao_desktop(l, top, w, h)
        if img is not None:
            resultado.append({"img": img, "titulo": j["titulo"],
                              "largura": w, "altura": h, "left": l, "top": top})
    return resultado


def capturar_agentes():
    """Captura o painel de Agentes / Negociação / Pressão / Descrição.
    Se as palavras-chave falharem, tenta a 3ª maior janela WDOFUT (fallback)."""
    palavras = [
        "negociacao", "negociação", "pressao", "pressão",
        "descricao", "descrição", "agentes", "corretoras", "ranking",
        "book de agentes", "comprador vendedor", "compradora vendedora",
        "hora agente", "5 negoc", "6 press", "7 descri",
        "6 agentes", "book agente",
        # abas que carregam a coluna de corretora por preco
        "ofertas", "livro de ofertas", "book de ofertas", "ofertante"
    ]
    img, msg = _capturar_por_palavras_forcado(palavras, "Agentes")
    if img is not None:
        st.session_state["ultimo_titulo_agentes"] = msg
        return img, msg

    # Fallback: pegar a 3ª maior janela WDOFUT (1ª=grafico, 2ª=T&T, 3ª=agentes)
    janelas_wdo = _encontrar_janelas_por_palavras(
        ["wdofut", "dolpro", "wdo", "dolar", "sim ", "simulador", "[r] wdofut"],
        area_minima=30000
    )
    janelas_wdo = sorted(janelas_wdo, key=lambda j: (j["r"]-j["l"])*(j["b"]-j["top"]), reverse=True)
    if len(janelas_wdo) >= 3:
        j = janelas_wdo[2]
        l, top, w, h = j["l"], j["top"], j["r"]-j["l"], j["b"]-j["top"]
        img = _bitblt_regiao_desktop(l, top, w, h)
        if img is not None:
            _msg = f"Agentes capturado (fallback 3ª janela WDOFUT): '{j['titulo']}' ({w}x{h}px em {l},{top})"
            st.session_state["ultimo_titulo_agentes"] = _msg
            return img, _msg
    # Último fallback: se tem só 2 janelas mas uma delas tem "sim" ou "simulador" (painel de agentes)
    janelas_sim = _encontrar_janelas_por_palavras(["sim ", "simulador", "216541", "book"], area_minima=30000)
    if janelas_sim:
        janelas_sim = sorted(janelas_sim, key=lambda j: (j["r"]-j["l"])*(j["b"]-j["top"]), reverse=True)
        j = janelas_sim[0]
        l, top, w, h = j["l"], j["top"], j["r"]-j["l"], j["b"]-j["top"]
        img = _bitblt_regiao_desktop(l, top, w, h)
        if img is not None:
            _msg = f"Agentes capturado (fallback janela Simulador): '{j['titulo']}' ({w}x{h}px em {l},{top})"
            st.session_state["ultimo_titulo_agentes"] = _msg
            return img, _msg
    # Fallback definitivo: o T&T na aba Ordem Original / Negocios JA traz os nomes
    # das corretoras nas colunas Compradora / Vendedora / Agressor.
    # Nesse layout nao existe janela "Negociacao" separada — e isso nao e erro.
    img_oo, msg_oo = capturar_times_trades_ordem_original()
    if img_oo is not None:
        _msg = f"Agentes capturado via T&T Ordem Original (Compradora/Vendedora/Agressor): {msg_oo}"
        st.session_state["ultimo_titulo_agentes"] = _msg
        st.session_state["origem_agentes"] = "tape_ordem_original"
        return img_oo, _msg

    img_tt, msg_tt = capturar_times_trades()
    if img_tt is not None:
        _msg = f"Agentes capturado via T&T Negocios (Comprador/Vendedor/Agressor): {msg_tt}"
        st.session_state["ultimo_titulo_agentes"] = _msg
        st.session_state["origem_agentes"] = "tape_negocios"
        return img_tt, _msg

    st.session_state["origem_agentes"] = "indisponivel"
    return None, "Agentes: sem painel dedicado e sem T&T capturavel neste momento."

def listar_todas_janelas_visiveis(area_minima=20000):
    """Lista TODAS as janelas visiveis do Windows, sem filtro por palavra-chave.
    Serve para descobrir o titulo real das janelas/abas do Profit."""
    linhas = []
    try:
        for w in gw.getAllWindows():
            try:
                titulo = (w.title or "").strip()
                l, top, r, b = win32gui.GetWindowRect(w._hWnd)
                larg, alt = r - l, b - top
                if larg * alt < area_minima:
                    continue
                if larg <= 0 or alt <= 0:
                    continue
                linhas.append({
                    "Titulo": titulo or "(sem titulo)",
                    "Left": l, "Top": top,
                    "Largura": larg, "Altura": alt,
                    "Area": larg * alt,
                    "hwnd": w._hWnd,
                })
            except Exception:
                continue
    except Exception:
        return []
    linhas.sort(key=lambda x: x["Area"], reverse=True)
    return linhas


def diagnosticar_janelas_profit():
    """Retorna lista de janelas relacionadas ao Profit com posicao/tamanho."""
    janelas = _enumerar_todas_janelas()
    relevantes = []
    for j in janelas:
        t_low = j["titulo"].lower()
        if any(p in t_low for p in [
            "profit", "nelogica", "SuperDom", "super dom", "livro", "times", "trades",
            "book", "boleta", "tape", "dom", "wdo", "dolar", "minuto",
            "1 dolar", "2 super", "3 livro", "4 times"
        ]):
            relevantes.append(j)
    return sorted(relevantes, key=lambda x: -x["area"])



# =========================
# UTILITARIOS
# =========================
def extrair_json(texto):
    if not texto: return None
    for fn in [
        lambda t: json.loads(t),
        lambda t: json.loads(t.replace("```json","").replace("```","").strip()),
        lambda t: json.loads(t[t.find("{"):t.rfind("}")+1]) if "{" in t else None,
    ]:
        try:
            r = fn(texto)
            if r: return r
        except Exception: pass
    return None


def num(v, p=0.0):
    """Converte texto em numero respeitando o formato brasileiro.

    O bug antigo: "5.129" (milhar sem decimais) virava 5.129 em vez de 5129.
    Preco, maxima e minima chegavam corrompidos e pos_range travava em 50.
    """
    try:
        if v is None: return p
        if isinstance(v, (int, float)): return float(v)
        v = str(v).strip().replace(" ", "")
        if not v: return p
        v = v.replace("R$", "").replace("%", "")
        tem_pt, tem_vg = "." in v, "," in v
        if tem_pt and tem_vg:
            v = v.replace(".", "").replace(",", ".")
        elif tem_vg:
            v = v.replace(",", ".")
        elif tem_pt:
            _partes = v.split(".")
            # 3 digitos apos o ultimo ponto = separador de milhar (5.129 / 5.129.500)
            if len(_partes) > 2 or len(_partes[-1]) == 3:
                v = v.replace(".", "")
        return float(v)
    except Exception: return p


def _set_state(chave, valor):
    """Escreve em session_state sem quebrar quando a chave pertence a um widget
    ja instanciado (StreamlitAPIException). Retorna True se conseguiu gravar."""
    try:
        st.session_state[chave] = valor
        return True
    except Exception:
        return False


def ts_evento(dados_tela):
    """
    Gera o timestamp do evento. No modo replay, SEMPRE usa a data/hora do replay
    (session_state.replay_data + replay_hora) — nunca cai para datetime.now().
    """
    if st.session_state.get("modo_replay"):
        # PRIORIDADE 1: relogio lido diretamente da tela do Profit (mais fiel)
        hora_tela = str(dados_tela.get("hora_replay") or "").strip()
        data_tela = str(dados_tela.get("data_replay") or "").strip()
        if "/" in data_tela and len(data_tela) == 10:
            _d, _m, _a = data_tela.split("/")
            data_tela = f"{_a}-{_m}-{_d}"

        data = data_tela if len(data_tela) == 10 else str(st.session_state.get("replay_data", "")).strip()
        hora = hora_tela if ":" in hora_tela else str(st.session_state.get("replay_hora", "")).strip()

        if data and hora:
            _p = hora.split(":")
            try:
                _hh = int(_p[0]); _mm = int(_p[1]); _ss = int(_p[2]) if len(_p) > 2 else 0
                return f"{data} {_hh:02d}:{_mm:02d}:{_ss:02d}"
            except Exception:
                return f"{data} {hora}"
        # Se replay ativo mas sem data/hora, tenta usar o que veio da tela
        data = data or dados_tela.get("data_replay") or dados_tela.get("data") or datetime.now().strftime("%Y-%m-%d")
        hora = hora or dados_tela.get("hora_replay") or dados_tela.get("hora") or datetime.now().strftime("%H:%M")
        return f"{data} {hora}:00" if len(hora) == 5 else f"{data} {hora}"

    # Modo real (nao replay)
    data = dados_tela.get("data_replay") or dados_tela.get("data") or datetime.now().strftime("%Y-%m-%d")
    hora = dados_tela.get("hora_replay") or dados_tela.get("hora") or ""
    if hora:
        try:
            if int(hora.split(":")[0]) < 9:
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception: pass

    if data and hora:
        for fmt in ["%Y-%m-%d %H:%M","%d/%m/%Y %H:%M","%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S"]:
            try: return datetime.strptime(f"{data} {hora}", fmt).strftime("%Y-%m-%d %H:%M:%S")
            except Exception: pass
            
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_hm(hora_str):
    try:
        p = str(hora_str).strip().split(":")
        return int(p[0])*60+int(p[1])
    except Exception: return None


# =========================
# LEITURA DA TELA COM IA
# =========================
def imagem_para_b64(img, largura_max=1280, qualidade=72):
    """Reduz o payload enviado a IA sem perder os numeros da tela.

    Latencia importa: cada segundo extra de inferencia custa deslocamento de preco
    na entrada. Redimensionar e recomprimir corta o Base64 quase pela metade
    mantendo os digitos legiveis.
    """
    try:
        _im = img
        if _im.mode not in ("RGB", "L"):
            _im = _im.convert("RGB")
        w, h = _im.size
        if w > largura_max:
            _im = _im.resize((largura_max, max(1, int(h * (largura_max / float(w))))), Image.LANCZOS)
        buf = BytesIO()
        _im.save(buf, format="JPEG", quality=qualidade, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        buf = BytesIO()
        img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()


def extrair_dados_tela(img, modo_replay=False):
    # Grafico precisa de mais resolucao: os numeros das medias sao pequenos.
    b64 = imagem_para_b64(img, largura_max=1500, qualidade=78)

    prompt = """
Extraia os dados objetivos visiveis na tela do Profit/Replay.
Responda apenas em JSON valido. Nao use markdown. Se nao conseguir ler um campo use 0.0 ou string vazia.
Para preco_atual use o fechamento marcado como F no topo. Nao invente valores.

CRITICO — VALIDE A ARITMETICA ANTES DE FECHAR O JSON:
1. "maxima" NUNCA pode ser menor que "minima". Se a leitura violar isso, releia os dois campos.
2. "preco_atual" TEM de estar entre "minima" e "maxima", inclusive. Se ficar fora, um dos tres numeros
   foi lido errado — releia e corrija antes de responder.
3. "abertura" tambem precisa estar dentro do intervalo minima-maxima.
4. Precos do WDO ficam na casa dos MILHARES (ex: 5127.50). Se ler algo como 5.13 ou 512, perdeu
   digitos: releia o numero inteiro.
5. Formato brasileiro usa ponto como separador de milhar: "5.127,50" vale 5127.50. Retorne SEMPRE
   em formato americano, sem separador de milhar: 5127.50.
6. Se um campo estiver ilegivel ou sobreposto, devolva 0.0 em vez de adivinhar. Zero e tratado como
   "nao lido"; um numero errado contamina toda a analise.

{
  "ativo": "", "timeframe": "",
  "data_replay": "data do replay no formato YYYY-MM-DD. Leia no CABECALHO da janela do grafico (ex: '28/07/2026 09:00:31' -> '2026-07-28') ou no painel Replay/Modos de Exibicao. NUNCA invente.",
  "hora_replay": "hora EXATA do replay no formato HH:MM:SS. Leia no CABECALHO da janela do grafico, ao lado da data (ex: '28/07/2026 09:00:31' -> '09:00:31'), ou no painel Replay onde aparece o cronometro (ex: '09:00:31'). Se so houver HH:MM, retorne HH:MM:00. Este campo e CRITICO: leia com atencao maxima.",
  "preco_atual": 0.0, "abertura": 0.0, "maxima": 0.0, "minima": 0.0,
  "vwap": 0.0, "ajuste": 0.0, "ptax": 0.0,
  "ajuste_anterior": "valor do AJUSTE DO PREGAO ANTERIOR. Procure o rotulo 'Prior Cote Ajuste', 'Ajuste Anterior' ou a linha horizontal rotulada 'Ajuste' no grafico. 0.0 se nao houver.",
  "maxima_anterior": "MAXIMA do pregao ANTERIOR (nao a de hoje). Leia a linha horizontal rotulada 'Maximo'/'Maxima' ou o topo dos candles do dia anterior visiveis a esquerda do separador de dias. 0.0 se nao conseguir.",
  "minima_anterior": "MINIMA do pregao ANTERIOR (nao a de hoje). Leia a linha rotulada 'Minimo'/'Minima' ou o fundo dos candles do dia anterior. 0.0 se nao conseguir.",
  "data_pregao_anterior": "data do pregao ANTERIOR visivel no eixo do grafico, formato YYYY-MM-DD (ex: eixo mostrando '13/ago' num replay de 2026 -> '2026-08-13'). String vazia se nao houver.",
  "mm9": 0.0, "mm20": 0.0, "mm50": 0.0, "mm200": 0.0,
  "volume": 0,
  "volume_financeiro": "volume FINANCEIRO da barra/histograma logo ABAIXO do grafico de candles. Leia exatamente como aparece, com o sufixo (ex: '1,25 B', '870 M', '15.400'). String vazia se nao conseguir ler.",
  "volume_financeiro_acumulado": "volume financeiro acumulado do dia, se visivel no rodape ou no painel de volume. Mesmo formato. String vazia se nao houver.",
  "padrao_candle": "identifique o padrão do último candle fechado. Use EXATAMENTE um destes valores: engolfo_alta, engolfo_baixa, pinbar_alta, pinbar_baixa, martelo, estrela_cadente, estrela_da_manha, estrela_da_tarde, marubozu_alta, marubozu_baixa, doji, harami, nenhum",
  "status_fluxo": "", "observacao_visual": ""
}
"""

    partes = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]

    content = chamar_openrouter(partes, temperature=0.0, timeout=40)
    if not content:
        return None

    parsed = extrair_json(content)
    if parsed is None:
        st.session_state["ultimo_erro_ia"] = "JSON nao extraido."
        return None

    return parsed


# =========================
# VALIDACAO
# =========================
def validar_leitura(dt):
    preco = num(dt.get("preco_atual"))
    maxima = num(dt.get("maxima"))
    minima = num(dt.get("minima"))
    erros = []
    if preco <= 0: erros.append("preco_invalido")
    # WDO negocia na casa dos milhares: 5.13 e leitura corrompida, nao preco.
    if 0 < preco < 1000: erros.append("preco_fora_de_escala")
    if maxima > 0 and minima > 0 and maxima < minima: erros.append("maxima<minima")
    # Tolerancia de 0,05 era apertada demais para OCR de tela: o preco atual
    # frequentemente e lido meio tick acima da maxima ja impressa.
    if preco > 0 and maxima > 0 and preco > maxima + 1.5: erros.append("preco>maxima")
    if preco > 0 and minima > 0 and preco < minima - 1.5: erros.append("preco<minima")
    for nome in ["vwap","mm9","mm20","mm50","mm200"]:
        v = num(dt.get(nome))
        if preco > 0 and v > 0 and abs(preco-v) > 150: erros.append(f"{nome}_distante")
    return {"consistente": len(erros)==0, "erros": erros}


# =========================
# CODIGO DO ATIVO (nome unico por sessao)
# =========================
def normalizar_ativo(nome):
    """Reduz o codigo lido da tela a forma canonica: raiz + vencimento."""
    t = str(nome or "").strip().upper().replace(" ", "")
    if not t:
        return ""
    m = re.match(r"^(WDO|DOL|WIN|IND|BIT|CCM|ICF)([FGHJKMNQUVXZ]?)(\d{0,4})", t)
    if not m:
        return t
    raiz, letra, ano = m.group(1), m.group(2), m.group(3)
    if letra and ano:
        return raiz + letra + ano[-2:]
    return raiz


def ativo_canonico(nome):
    """WDOU26, WDO26 e WDO apareciam na MESMA sessao e quebravam qualquer
    agrupamento do log. O primeiro codigo COMPLETO lido vale para a sessao;
    leituras truncadas passam a herdar esse codigo."""
    n = normalizar_ativo(nome)
    try:
        fixo = str(st.session_state.get("ativo_sessao", "") or "")
    except Exception:
        fixo = ""
    completo = bool(re.match(r"^(WDO|DOL|WIN|IND|BIT|CCM|ICF)[FGHJKMNQUVXZ]\d{2}$", n))
    if completo:
        try:
            st.session_state["ativo_sessao"] = n
        except Exception:
            pass
        return n
    if fixo and n and fixo.startswith(n[:3]):
        return fixo
    return n or fixo


_validar_leitura_bruto = validar_leitura


def validar_leitura(dt):
    """Normaliza o ativo ANTES de validar: painel, CSV e gatekeeper gravam
    sempre o mesmo nome."""
    if isinstance(dt, dict):
        _a = ativo_canonico(dt.get("ativo", ""))
        if _a:
            dt["ativo"] = _a
    return _validar_leitura_bruto(dt)


# =========================
# REGIME DE MERCADO
# =========================
def _carregar_hist_leituras_persistido():
    try:
        if os.path.exists(ARQ_HIST_LEITURAS):
            with open(ARQ_HIST_LEITURAS, "r", encoding="utf-8") as f:
                bruto = json.load(f)
            if isinstance(bruto, dict):
                return bruto
    except Exception:
        pass
    return {}


def _salvar_hist_leituras_persistido(hist_map):
    try:
        with open(ARQ_HIST_LEITURAS, "w", encoding="utf-8") as f:
            json.dump(hist_map, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _chave_hist_ativo(dados_tela):
    ativo = ativo_canonico((dados_tela or {}).get("ativo", "")) or "ATIVO"
    data_ref = str((dados_tela or {}).get("data") or datetime.now().strftime("%Y-%m-%d"))
    return f"{ativo}::{data_ref}"


def registrar_leitura_historico(dados_tela):
    """Guarda as ultimas 8 leituras para calcular momentum e inclinacao.
    Persiste por ativo/sessao para sobreviver a reinicio do app."""
    chave = _chave_hist_ativo(dados_tela)
    hist_map = _carregar_hist_leituras_persistido()
    h = hist_map.get(chave, st.session_state.get("hist_leituras", []))
    if not isinstance(h, list):
        h = []
    leitura = {
        "preco": num(dados_tela.get("preco_atual", 0)),
        "mm9": num(dados_tela.get("mm9", 0)),
        "mm20": num(dados_tela.get("mm20", 0)),
        "mm50": num(dados_tela.get("mm50", 0)),
        "hora": str(dados_tela.get("hora_replay") or dados_tela.get("hora") or ""),
        "volume": num(dados_tela.get("volume_candle", dados_tela.get("volume", 0))),
        "vwap": num(dados_tela.get("vwap", 0)),
    }
    if not h or any(leitura.get(k) != h[0].get(k) for k in ("preco", "mm9", "mm20", "mm50", "hora")):
        h.insert(0, leitura)
    # Serie ampliada de 8 para 40 leituras: Bandas de Bollinger (20 periodos) e
    # IFR (14 periodos) nao fecham a conta com apenas 8 pontos.
    h = h[:40]
    hist_map[chave] = h
    _salvar_hist_leituras_persistido(hist_map)
    st.session_state["hist_leituras"] = h
    st.session_state["hist_leituras_chave"] = chave
    return h


# =============================================================================
# BANDAS DE BOLLINGER — 20 periodos, 2 desvios
# No mini dolar em consolidacao as bandas viram barreira de preco: toque na
# superior com pavio = sobrecompra e scalp contra, buscando a media central.
# =============================================================================
ARQ_RANGE_DIA = "range_dia.json"
# Amplitude minima para o range do dia ser considerado utilizavel.
AMPLITUDE_MINIMA_RANGE = 3.0


def _carregar_range_dia():
    try:
        if os.path.exists(ARQ_RANGE_DIA):
            with open(ARQ_RANGE_DIA, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def range_dia_acumulado(dados_tela):
    """Maxima e minima REAIS do dia, acumuladas leitura a leitura.

    A tela entrega o extremo do candle corrente, nao o do pregao. Sem isso o
    PosRangeDia vivia em 0 ou 100 e todo filtro de range ficava sem sentido.
    Acumula por ativo + data, persistido em disco, e incorpora o preco atual.
    """
    d = dados_tela or {}
    preco = num(d.get("preco_atual", 0))
    max_tela = num(d.get("maxima", 0))
    min_tela = num(d.get("minima", 0))
    ativo = ativo_canonico(d.get("ativo", "")) or "ATIVO"
    data_ref = str(d.get("data") or datetime.now().strftime("%Y-%m-%d"))[:10]
    chave = f"{ativo}::{data_ref}"

    mapa = _carregar_range_dia()
    reg = mapa.get(chave) if isinstance(mapa.get(chave), dict) else {}
    maxima = num(reg.get("maxima", 0))
    minima = num(reg.get("minima", 0))

    for v in (max_tela, preco):
        if v > 0:
            maxima = v if maxima <= 0 else max(maxima, v)
    for v in (min_tela, preco):
        if v > 0:
            minima = v if minima <= 0 else min(minima, v)

    if maxima > 0 and minima > 0:
        mapa[chave] = {"maxima": round(maxima, 2), "minima": round(minima, 2),
                       "atualizado": datetime.now().strftime("%H:%M:%S"),
                       "leituras": int(num(reg.get("leituras", 0))) + 1}
        # Mantem apenas os ultimos 10 dias de registro.
        if len(mapa) > 10:
            for k in sorted(mapa.keys())[:-10]:
                mapa.pop(k, None)
        try:
            with open(ARQ_RANGE_DIA, "w", encoding="utf-8") as f:
                json.dump(mapa, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    amplitude = round(maxima - minima, 2) if (maxima > 0 and minima > 0) else 0.0
    return {"maxima": maxima, "minima": minima, "amplitude": amplitude,
            "valido": amplitude >= AMPLITUDE_MINIMA_RANGE,
            "origem_tela": round(max_tela - min_tela, 2) if (max_tela > 0 and min_tela > 0) else 0.0,
            "leituras": int(num((mapa.get(chave) or {}).get("leituras", 0)))}


BOLLINGER_PERIODOS = 20
BOLLINGER_DESVIOS = 2.0
# Largura relativa abaixo da qual as bandas estao "estreitas" (consolidacao).
BOLLINGER_ESTREITA_PCT = 0.12
# Distancia da banda, em pontos, para considerar que o preco a tocou.
BOLLINGER_TOLERANCIA_TOQUE = 1.5


def calcular_bollinger(dados_tela, hist=None):
    """Bandas de Bollinger sobre a serie de leituras.

    Centro: MM20 da tela quando disponivel (e a media do grafico operado);
    na falta dela, a media da propria serie.
    """
    hist = hist if hist is not None else st.session_state.get("hist_leituras", [])
    precos = [num(x.get("preco", 0)) for x in (hist or []) if num(x.get("preco", 0)) > 0]
    preco = num((dados_tela or {}).get("preco_atual", 0))
    vazio = {"valido": False, "superior": 0.0, "inferior": 0.0, "central": 0.0,
             "largura": 0.0, "largura_pct": 0.0, "posicao": -1.0, "estado": "indefinido",
             "estreita": False, "toque_superior": False, "toque_inferior": False,
             "amostra": len(precos)}
    if preco <= 0 or len(precos) < 6:
        return vazio

    serie = precos[:BOLLINGER_PERIODOS]
    media_serie = sum(serie) / len(serie)
    variancia = sum((p - media_serie) ** 2 for p in serie) / len(serie)
    desvio = variancia ** 0.5
    if desvio <= 0:
        return vazio

    central = num((dados_tela or {}).get("mm20", 0)) or media_serie
    superior = round(central + BOLLINGER_DESVIOS * desvio, 2)
    inferior = round(central - BOLLINGER_DESVIOS * desvio, 2)
    largura = round(superior - inferior, 2)
    largura_pct = round((largura / central) * 100, 3) if central > 0 else 0.0

    posicao = -1.0
    if largura > 0:
        posicao = round(((preco - inferior) / largura) * 100, 1)
        posicao = max(-20.0, min(120.0, posicao))

    toque_sup = preco >= (superior - BOLLINGER_TOLERANCIA_TOQUE)
    toque_inf = preco <= (inferior + BOLLINGER_TOLERANCIA_TOQUE)
    if toque_sup:
        estado = "sobrecompra"
    elif toque_inf:
        estado = "sobrevenda"
    elif abs(preco - central) <= BOLLINGER_TOLERANCIA_TOQUE:
        estado = "na_media"
    else:
        estado = "dentro"

    return {"valido": True, "superior": superior, "inferior": inferior,
            "central": round(central, 2), "largura": largura,
            "largura_pct": largura_pct, "posicao": posicao, "estado": estado,
            "estreita": largura_pct <= BOLLINGER_ESTREITA_PCT,
            "toque_superior": bool(toque_sup), "toque_inferior": bool(toque_inf),
            "desvio": round(desvio, 2), "amostra": len(serie)}


# =============================================================================
# IFR / RSI — 14 periodos
# No mini dolar o valor absoluto importa menos que a DIVERGENCIA: preco faz nova
# maxima e o IFR nao acompanha = a perna perdeu forca.
# =============================================================================
IFR_PERIODOS = 14
IFR_SOBRECOMPRA = 70.0
IFR_SOBREVENDA = 30.0


def calcular_ifr(dados_tela=None, hist=None):
    """IFR (RSI) de Wilder simplificado sobre a serie de leituras."""
    hist = hist if hist is not None else st.session_state.get("hist_leituras", [])
    precos = [num(x.get("preco", 0)) for x in (hist or []) if num(x.get("preco", 0)) > 0]
    vazio = {"valido": False, "ifr": 50.0, "estado": "indefinido",
             "divergencia": "", "amostra": len(precos)}
    # Com menos de 10 leituras o IFR devolvia 50 ou 100 sem base real e
    # poluia o log. Abaixo disso ele fica declaradamente invalido.
    if len(precos) < 10:
        vazio["motivo"] = f"série curta ({len(precos)}/10 leituras)"
        return vazio

    # A serie vem do mais recente para o mais antigo: inverte para cronologica.
    serie = list(reversed(precos[:IFR_PERIODOS + 1]))
    ganhos, perdas = [], []
    for i in range(1, len(serie)):
        d = serie[i] - serie[i - 1]
        ganhos.append(max(0.0, d))
        perdas.append(max(0.0, -d))
    if not ganhos:
        return vazio
    media_g = sum(ganhos) / len(ganhos)
    media_p = sum(perdas) / len(perdas)
    if media_p <= 0 or media_g <= 0:
        # Serie sem nenhuma perda (ou sem nenhum ganho) nao produz IFR real:
        # devolvia 100 ou 0 artificiais e contaminava o score.
        vazio["motivo"] = "série sem oscilação nos dois sentidos"
        return vazio
    rs = media_g / media_p
    ifr = 100.0 - (100.0 / (1.0 + rs))
    # Amplitude irrisoria tambem nao sustenta leitura de forca relativa.
    if (max(serie) - min(serie)) < 1.0:
        vazio["motivo"] = "variação menor que 1 ponto na janela"
        return vazio
    ifr = round(max(1.0, min(99.0, ifr)), 1)

    if ifr >= IFR_SOBRECOMPRA:
        estado = "sobrecompra"
    elif ifr <= IFR_SOBREVENDA:
        estado = "sobrevenda"
    else:
        estado = "neutro"

    # ---- DIVERGENCIA: o sinal mais util do IFR no mini dolar ----
    divergencia = ""
    ifr_ant = num(st.session_state.get("ultimo_ifr", 0))
    preco_max_ant = num(st.session_state.get("ifr_preco_maxima", 0))
    preco_min_ant = num(st.session_state.get("ifr_preco_minima", 0))
    preco_now = precos[0]
    if preco_max_ant > 0 and ifr_ant > 0:
        if preco_now > preco_max_ant and ifr < ifr_ant:
            divergencia = "baixista"      # nova maxima sem forca -> perna cansada
    if preco_min_ant > 0 and ifr_ant > 0 and not divergencia:
        if preco_now < preco_min_ant and ifr > ifr_ant:
            divergencia = "altista"       # novo fundo sem forca -> repique
    st.session_state["ultimo_ifr"] = ifr
    st.session_state["ifr_preco_maxima"] = max(preco_max_ant, preco_now)
    st.session_state["ifr_preco_minima"] = (min(preco_min_ant, preco_now)
                                            if preco_min_ant > 0 else preco_now)

    return {"valido": True, "ifr": ifr, "estado": estado,
            "divergencia": divergencia, "amostra": len(serie)}


# =============================================================================
# SETUP DE SCALP — VWAP, Ajuste e Volume
# Primeiro toque do dia na VWAP e no Ajuste costuma ter defesa institucional:
# e o scalp de 2 a 4 pontos.
# =============================================================================
TOLERANCIA_TOQUE_VWAP = 2.0
TOLERANCIA_TOQUE_AJUSTE = 2.0
# Volume baixo no toque favorece o repique; volume muito alto sugere rompimento.
VOLUME_SCALP_ALTO = 3.0     # multiplo da media recente


def _registrar_toque(chave_estado, encostou, data_ref):
    """Marca o PRIMEIRO toque do dia numa referencia. Devolve True so na 1a vez."""
    estado = st.session_state.get(chave_estado)
    if not isinstance(estado, dict) or estado.get("dia") != data_ref:
        estado = {"dia": data_ref, "tocou": False}
    primeiro = bool(encostou and not estado["tocou"])
    if encostou:
        estado["tocou"] = True
    st.session_state[chave_estado] = estado
    return primeiro


def avaliar_setup_scalp(dados_tela, hist=None, volume_atual=0.0):
    """Gatilhos de scalp: choque com VWAP, primeiro toque no Ajuste e volume."""
    d = dados_tela or {}
    preco = num(d.get("preco_atual", 0))
    vwap = num(d.get("vwap", 0))
    ajuste = num(d.get("ajuste", 0))
    dia = str(d.get("data") or datetime.now().strftime("%Y-%m-%d"))[:10]
    saida = {"vwap_toque": False, "vwap_primeiro": False, "vwap_dist": 0.0,
             "ajuste_toque": False, "ajuste_primeiro": False, "ajuste_dist": 0.0,
             "volume_relativo": 0.0, "volume_perfil": "indefinido",
             "direcao_scalp": "", "motivo": ""}
    if preco <= 0:
        return saida

    if vwap > 0:
        dist_v = abs(preco - vwap)
        saida["vwap_dist"] = round(dist_v, 2)
        saida["vwap_toque"] = dist_v <= TOLERANCIA_TOQUE_VWAP
        saida["vwap_primeiro"] = _registrar_toque("scalp_toque_vwap",
                                                  saida["vwap_toque"], dia)
    if ajuste > 0:
        dist_a = abs(preco - ajuste)
        saida["ajuste_dist"] = round(dist_a, 2)
        saida["ajuste_toque"] = dist_a <= TOLERANCIA_TOQUE_AJUSTE
        saida["ajuste_primeiro"] = _registrar_toque("scalp_toque_ajuste",
                                                    saida["ajuste_toque"], dia)

    # ---- VOLUME NO TOQUE ----
    # Volume baixo na referencia = bate e volta (scalp perfeito).
    # Volume muito alto = rompimento agressivo, nao operar contra.
    hist = hist if hist is not None else st.session_state.get("hist_leituras", [])
    vols = [num(x.get("volume", 0)) for x in (hist or []) if num(x.get("volume", 0)) > 0]
    # Volume nao lido nesta leitura: usa o ultimo valor valido da serie, para
    # o perfil nao ficar indefinido a cada candle sem captura.
    if volume_atual <= 0:
        # Contratos nao lidos: tenta o volume financeiro da barra, depois o
        # ultimo valor valido da serie.
        _vf = (num((dados_tela or {}).get("volume_financeiro", 0))
               or num((dados_tela or {}).get("volume_financeiro_acumulado", 0)))
        if _vf > 0:
            volume_atual = _vf
            saida["volume_estimado"] = True
        elif vols:
            volume_atual = vols[0]
            saida["volume_estimado"] = True
    if volume_atual > 0 and vols:
        media_vol = sum(vols[:10]) / len(vols[:10])
        if media_vol > 0:
            rel = round(volume_atual / media_vol, 2)
            saida["volume_relativo"] = rel
            if rel >= VOLUME_SCALP_ALTO:
                saida["volume_perfil"] = "rompimento"
            elif rel <= 0.7:
                saida["volume_perfil"] = "fraco_favorece_repique"
            else:
                saida["volume_perfil"] = "normal"

    # ---- DIRECAO DO SCALP ----
    if saida["vwap_primeiro"] and vwap > 0:
        saida["direcao_scalp"] = "compra" if preco < vwap else "venda"
        saida["motivo"] = f"Primeiro toque do dia na VWAP {vwap:.2f} — defesa institucional."
    elif saida["ajuste_primeiro"] and ajuste > 0:
        saida["direcao_scalp"] = "compra" if preco < ajuste else "venda"
        saida["motivo"] = f"Primeiro toque do dia no Ajuste {ajuste:.2f} — repique esperado."
    if saida["volume_perfil"] == "rompimento" and saida["direcao_scalp"]:
        saida["direcao_scalp"] = ""
        saida["motivo"] += " Cancelado: volume de rompimento agressivo."
    return saida


def calcular_momentum(dados_tela):
    """Mede a DIRECAO do movimento (nao apenas a posicao vs medias).

    Retorna dict com:
      delta_preco     — variacao do preco desde a leitura anterior
      delta_3         — variacao acumulada nas ultimas 3 leituras
      inclinacao_mm9  — a MM9 esta subindo ou caindo
      inclinacao_mm20 — idem MM20
      momentum        — 'alta_forte' | 'alta' | 'neutro' | 'baixa' | 'baixa_forte'
      pos_range       — posicao do preco no range do dia (0 = minima, 100 = maxima)
    """
    hist = st.session_state.get("hist_leituras", [])
    preco = num(dados_tela.get("preco_atual", 0))
    maxima = num(dados_tela.get("maxima", 0))
    minima = num(dados_tela.get("minima", 0))

    # -1 significa "nao calculavel". Devolver 50 fazia todo filtro de range
    # passar como se o preco estivesse sempre no meio do dia.
    # O extremo vem do range ACUMULADO do pregao, nao do candle da tela.
    try:
        _rg = range_dia_acumulado(dados_tela)
        st.session_state["ultimo_range_dia"] = _rg
        if _rg.get("valido"):
            maxima, minima = _rg["maxima"], _rg["minima"]
    except Exception:
        _rg = {"amplitude": 0.0, "valido": False}
    pos_range = -1.0
    if maxima > minima > 0 and preco > 0 and (maxima - minima) >= AMPLITUDE_MINIMA_RANGE:
        pos_range = round(((preco - minima) / (maxima - minima)) * 100, 1)
        pos_range = max(0.0, min(100.0, pos_range))

    if len(hist) < 2:
        _vazio = {"delta_preco": 0.0, "delta_3": 0.0, "inclinacao_mm9": 0.0,
                  "inclinacao_mm20": 0.0, "inclinacao_mm9_media": 0.0,
                  "momentum": "neutro", "momentum_bruto": "neutro",
                  "momentum_confirmado": False, "leituras_mesma_direcao": 0,
                  "delta_3_valido": False,
                  "pos_range": pos_range, "leituras": len(hist)}
        st.session_state["ultimo_momentum"] = _vazio
        return _vazio

    ant = hist[1]
    delta_preco = round(preco - num(ant.get("preco", 0)), 2) if num(ant.get("preco", 0)) > 0 else 0.0

    # delta_3 precisa de TRES leituras. Com historico curto ele repetia
    # delta_preco e uma unica leitura bastava para gerar 'forte'.
    _i3 = min(3, len(hist) - 1)
    ref3 = hist[_i3]
    delta_3_valido = _i3 >= 2
    delta_3 = 0.0
    if delta_3_valido and num(ref3.get("preco", 0)) > 0:
        delta_3 = round(preco - num(ref3.get("preco", 0)), 2)

    mm9_now, mm9_ant = num(dados_tela.get("mm9", 0)), num(ant.get("mm9", 0))
    mm20_now, mm20_ant = num(dados_tela.get("mm20", 0)), num(ant.get("mm20", 0))
    inc9  = round(mm9_now - mm9_ant, 2) if (mm9_now > 0 and mm9_ant > 0) else 0.0
    inc20 = round(mm20_now - mm20_ant, 2) if (mm20_now > 0 and mm20_ant > 0) else 0.0

    pontos = 0
    if delta_preco >= 2.0: pontos += 2
    elif delta_preco >= 0.5: pontos += 1
    elif delta_preco <= -2.0: pontos -= 2
    elif delta_preco <= -0.5: pontos -= 1
    if delta_3 >= 4.0: pontos += 2
    elif delta_3 >= 1.5: pontos += 1
    elif delta_3 <= -4.0: pontos -= 2
    elif delta_3 <= -1.5: pontos -= 1
    if inc9 > 0.1: pontos += 1
    elif inc9 < -0.1: pontos -= 1
    if inc20 > 0.1: pontos += 1
    elif inc20 < -0.1: pontos -= 1

    if pontos >= 4:   mom_bruto = "alta_forte"
    elif pontos >= 2: mom_bruto = "alta"
    elif pontos <= -4: mom_bruto = "baixa_forte"
    elif pontos <= -2: mom_bruto = "baixa"
    else: mom_bruto = "neutro"

    # ---- CONFIRMACAO: o campo era reativo e virava em ~70 segundos ----
    # (1) 'forte' exige a inclinacao da MM9 na mesma direcao. A MM9 e o unico
    #     campo que nao inverte entre duas leituras consecutivas.
    if mom_bruto == "alta_forte" and inc9 <= 0.0:
        mom_bruto = "alta"
    elif mom_bruto == "baixa_forte" and inc9 >= 0.0:
        mom_bruto = "baixa"

    # (2) Media das duas ultimas inclinacoes da MM9: filtra o ruido de 1 leitura.
    inc9_media = inc9
    if len(hist) > 2:
        _m9_2 = num(hist[2].get("mm9", 0))
        if _m9_2 > 0 and mm9_ant > 0:
            inc9_media = round(((mm9_now - mm9_ant) + (mm9_ant - _m9_2)) / 2.0, 2)

    def _dir_mom(m):
        if m in ("alta", "alta_forte"): return 1
        if m in ("baixa", "baixa_forte"): return -1
        return 0

    # (3) Persistencia: a direcao so inverte com DUAS leituras na nova direcao.
    #     Uma leitura isolada de sinal oposto rebaixa a intensidade, nao inverte
    #     o vies — era isso que gerava venda no meio de uma perna de alta.
    hist_mom = st.session_state.get("hist_momentum", []) or []
    _d_now = _dir_mom(mom_bruto)
    _d_ant = _dir_mom(hist_mom[0]) if hist_mom else 0
    _d_ant2 = _dir_mom(hist_mom[1]) if len(hist_mom) > 1 else 0
    mom = mom_bruto
    if _d_now != 0 and _d_ant != 0 and _d_now != _d_ant and _d_ant2 == _d_ant:
        mom = "alta" if _d_ant > 0 else "baixa"

    seq = 1 if _dir_mom(mom) != 0 else 0
    for _m in hist_mom:
        if _dir_mom(mom) != 0 and _dir_mom(_m) == _dir_mom(mom):
            seq += 1
        else:
            break
    st.session_state["hist_momentum"] = ([mom_bruto] + hist_mom)[:6]

    saida = {"delta_preco": delta_preco, "delta_3": delta_3,
             "inclinacao_mm9": inc9, "inclinacao_mm20": inc20,
             "inclinacao_mm9_media": inc9_media,
             "momentum": mom, "momentum_bruto": mom_bruto,
             "momentum_confirmado": seq >= MIN_LEITURAS_CONFIRMA_MOMENTUM,
             "leituras_mesma_direcao": seq,
             "delta_3_valido": delta_3_valido,
             "pos_range": pos_range, "leituras": len(hist)}
    st.session_state["ultimo_momentum"] = saida
    return saida


def peso_pmi_eua(macro):
    """Converte o PMI dos EUA em vies para o Mini Dolar.

    PMI forte (>52)  -> economia americana aquecida -> dolar tende a SUBIR  -> vies comprador
    PMI fraco (<48)  -> economia desacelerando      -> dolar tende a CAIR   -> vies vendedor
    """
    if not macro:
        return {"pmi": None, "vies": "neutro", "peso": 0, "descricao": "PMI indisponivel"}

    valores = []
    for chave in ("PMI_ISM_SERVICOS", "PMI_SP_SERVICOS", "PMI_COMPOSTO", "PMI_MANUFATURA", "PMI"):
        v = num(macro.get(chave))
        if 20 < v < 80:
            valores.append(v)
    if not valores:
        return {"pmi": None, "vies": "neutro", "peso": 0, "descricao": "PMI indisponivel"}

    pmi = round(sum(valores) / len(valores), 1)
    if pmi >= 54:   return {"pmi": pmi, "vies": "comprador", "peso": 2,  "descricao": f"PMI EUA {pmi} — expansao forte, dolar favorecido"}
    if pmi >= 52:   return {"pmi": pmi, "vies": "comprador", "peso": 1,  "descricao": f"PMI EUA {pmi} — expansao moderada"}
    if pmi <= 46:   return {"pmi": pmi, "vies": "vendedor",  "peso": -2, "descricao": f"PMI EUA {pmi} — contracao forte, dolar pressionado"}
    if pmi <= 48:   return {"pmi": pmi, "vies": "vendedor",  "peso": -1, "descricao": f"PMI EUA {pmi} — contracao moderada"}
    return {"pmi": pmi, "vies": "neutro", "peso": 0, "descricao": f"PMI EUA {pmi} — zona neutra"}


def classificar_regime(preco, vwap, ajuste, mm9, mm20, mm50, mm200, momentum=None):
    if preco <= 0: return "inconsistente"
    
    # Tolerância mais ampla para aceitar tendência mesmo com oscilações curtas
    av = vwap > 0 and preco >= vwap - 2.0
    bv = vwap > 0 and preco <= vwap + 2.0
    a9 = mm9 > 0 and preco >= mm9 - 2.0
    b9 = mm9 > 0 and preco <= mm9 + 2.0
    a20 = mm20 > 0 and preco >= mm20 - 2.0
    b20 = mm20 > 0 and preco <= mm20 + 2.0

    # MOMENTUM tem prioridade: medias sao atrasadas e invertem o sinal
    # em repiques de fundo / rejeicoes de topo.
    if momentum:
        _m = momentum.get("momentum", "neutro")
        _pr = momentum.get("pos_range", 50.0)
        if _m == "alta_forte": return "trend_up"
        if _m == "baixa_forte": return "trend_down"
        # Preco subindo no terco inferior do range = repique de fundo (compra)
        if _m == "alta" and _pr <= 40: return "pullback_up"
        # Preco caindo no terco superior do range = rejeicao de topo (venda)
        if _m == "baixa" and _pr >= 60: return "pullback_down"
        if _m == "alta": return "trend_up"
        if _m == "baixa": return "trend_down"

    if av and a9 and a20: return "trend_up"
    if bv and b9 and b20: return "trend_down"
    
    # Se o preço estiver acima da MM9, já considera pullback de alta ou tendência leve
    if mm9 > 0 and preco > mm9: return "trend_up"
    if mm9 > 0 and preco < mm9: return "trend_down"

    return "trend_up" # Padrão permissivo: evita o bloqueio por "misto"


# =========================
# LIMIAR DE SEGURANCA
# =========================
def calcular_limiar_seguranca(preco, vwap, ajuste, mm9, mm20, mm50, mm200, rr, score, score_min):
    """
    Retorna um valor de 0-100 representando a qualidade do setup.
    >= 70: setup forte (verde)
    40-69: setup medio (amarelo)
    < 40: setup fraco (vermelho)
    """
    pontos = 0
    # RR (peso 30)
    if rr >= 2.0: pontos += 30
    elif rr >= 1.5: pontos += 20
    elif rr >= 1.0: pontos += 10
    # Score vs minimo (peso 30)
    if score_min > 0:
        pct_score = min(1.0, score / score_min)
        pontos += int(pct_score * 30)
    # Distancia VWAP (peso 20): quanto mais perto melhor (menos de 10 pts)
    if vwap > 0:
        dist_v = abs(preco - vwap)
        if dist_v <= 5: pontos += 20
        elif dist_v <= 10: pontos += 12
        elif dist_v <= 20: pontos += 6
    # Ajuste (peso 20)
    if ajuste > 0:
        dist_a = abs(preco - ajuste)
        if dist_a <= 5: pontos += 20
        elif dist_a <= 15: pontos += 12
        elif dist_a <= 30: pontos += 6
    return min(100, pontos)


# =========================
# ESTRATEGIA E SCORE POR HORARIO
# =========================
# Zonas calibradas com base nos dados históricos:
# - Antes das 09:30: alta volatilidade na abertura → score +2
# - 09:30-10:00: abertura digerindo → score normal
# - 10:00-14:00: melhor janela do dia → score base
# - 14:00-16:00: tarde produtiva → score base
# - Após 16:00: volume baixo, movimentos falsos → score +2
def ajuste_score_horario(minutos):
    """
    Retorna quantos pontos extras são exigidos no score conforme o horário.
    Valores negativos = MAIS permissivo (afrouxa). Positivos = ENDURECE.
    """
    if minutos is None:
        return 0
    # ABERTURA (09:00 às 09:45): faixa de pior desempenho medido — ENDURECE.
    # Antes afrouxava em 1 ponto, o que ajudou a produzir 0 acertos em 4 trades.
    if 9*60 <= minutos < 9*60+45:
        return 2
    # ALMOÇO (12:00 às 13:00): saldo de -5,0 pts na amostragem — deixa de afrouxar.
    if 12*60 <= minutos < 13*60:
        return 1
    # 13:00 às 14:00 ficou positivo (+5,5 pts): mantem neutro.
    if 13*60 <= minutos < 14*60:
        return 0
    # Após 16:00 — volume baixo mas movimentos institucionais válidos: neutro
    if minutos >= 16*60:
        return 0
    # Antes das 09:15 ou entre 09:45 e 10:00 — abertura ainda muito errática
    if minutos < 9*60+15 or (minutos >= 9*60+45 and minutos < 10*60):
        return 1
    # 10:00–12:00 e 14:00–16:00 — melhor janela, sem penalidade
    return 0


def estrategia_por_horario(hora_str, regime, vies_anterior):
    if regime in ["range","misto","inconsistente"]: return "Conservador"
    minutos = parse_hm(hora_str)
    if minutos is None:
        return "Agressividade Média" if regime in ["trend_up","trend_down","pullback_up","pullback_down"] else "Conservador"
    # Antes das 09:30: usa estratégia conforme regime mas score será endurecido
    if minutos < 9*60+30:
        if regime in ["trend_up","trend_down"]:
            return "Agressividade Média"
        return "Conservador"
    # 09:30–10:00
    if minutos < 10*60:
        if regime in ["trend_up","trend_down"]:
            if (regime=="trend_up" and vies_anterior=="comprador") or (regime=="trend_down" and vies_anterior=="vendedor"):
                return "Agressividade Alta"
            return "Agressividade Média"
        return "Conservador"
    if 10*60 <= minutos < 11*60+30: return "Agressividade Média"
    if 11*60+30 <= minutos < 13*60+30: return "Conservador"
    if 13*60+30 <= minutos < 16*60: return "Agressividade Média"
    # Após 16:00: score será endurecido, estratégia mantida
    return "Agressividade Média" if regime in ["trend_up","trend_down"] else "Conservador"


# =========================
# SCORE
# =========================
def calcular_score(preco, vwap, ajuste, mm9, mm20, mm50, mm200, regime, acao):
    s = 0
    if acao == "compra":
        if vwap>0 and preco>vwap: s+=1
        if mm9>0 and preco>mm9: s+=1
        if mm20>0 and preco>mm20: s+=1
        if mm50>0 and preco>mm50: s+=1
        if mm200>0 and preco>mm200: s+=1
        if ajuste>0 and preco>ajuste: s+=1
        if regime in ["trend_up","pullback_up"]: s+=1
    elif acao == "venda":
        if vwap>0 and preco<vwap: s+=1
        if mm9>0 and preco<mm9: s+=1
        if mm20>0 and preco<mm20: s+=1
        if mm50>0 and preco<mm50: s+=1
        if mm200>0 and preco<mm200: s+=1
        if ajuste>0 and preco<ajuste: s+=1
        if regime in ["trend_down","pullback_down"]: s+=1
    return s


# =========================
# CLASSIFICACAO AVANCADA
# =========================
def avaliar_estrategia_liquidez_e_rejeicao(dados_tela, contexto, fechamento_ant):
    """
    Combina a Estratégia de Rompimento Falso (Armadilha de Liquidez) com
    o Teste em Zona de Liquidez/Fibonacci com Rejeição de Candle.
    Retorna dict com {tipo, estrategia, descricao}.
    tipo: 'compra' / 'venda' / 'espera'
    """
    preco = num(dados_tela.get("preco_atual", 0))
    maxima = num(dados_tela.get("maxima", 0))
    minima = num(dados_tela.get("minima", 0))
    padrao = str(dados_tela.get("padrao_candle", "")).lower().strip()
    vies_macro = str(contexto.get("vies_anterior", "indefinido")).lower()

    fib = fechamento_ant.get("fibonacci_diario", {}) if fechamento_ant else {}
    niveis_fib = [num(fib.get("nivel_382", 0)), num(fib.get("nivel_50", 0)), num(fib.get("nivel_618", 0))]

    sinal_operacional = {
        "tipo": "espera",
        "estrategia": "Nenhuma",
        "descricao": "Aguardando confluência de liquidez e rejeição.",
    }

    if preco <= 0:
        return sinal_operacional

    # Proximidade com zonas fortes (Fibonacci ou máx/mín do dia anterior)
    perto_zona_forte = any(n > 0 and abs(preco - n) <= 4.0 for n in niveis_fib)
    perto_extrema = (maxima > 0 and abs(preco - maxima) <= 3.0) or (minima > 0 and abs(preco - minima) <= 3.0)

    # Candles de rejeição
    rejeicao_alta = padrao in ["martelo", "pinbar_alta", "estrela_da_manha", "engolfo_alta"]
    rejeicao_baixa = padrao in ["estrela_cadente", "pinbar_baixa", "estrela_da_tarde", "engolfo_baixa"]

    # =========================================================================
    # CONDIÇÃO 1 — TESTE NA ZONA DE LIQUIDEZ COM REJEIÇÃO
    # =========================================================================
    if perto_zona_forte or perto_extrema:
        if vies_macro in ["vendedor", "neutro"] and rejeicao_baixa:
            return {
                "tipo": "venda",
                "estrategia": "Teste em Zona de Liquidez + Rejeição (Estrela Cadente/Pinbar)",
                "descricao": f"🔴 O preço testou zona de referência com rejeição ({padrao}) a favor do viés.",
            }
        elif vies_macro in ["comprador", "neutro"] and rejeicao_alta:
            return {
                "tipo": "compra",
                "estrategia": "Teste em Zona de Liquidez + Rejeição (Martelo/Pinbar)",
                "descricao": f"🟢 O preço testou zona de suporte/Fibonacci com rejeição ({padrao}) a favor do viés.",
            }

    # =========================================================================
    # CONDIÇÃO 2 — ROMPIMENTO FALSO / ARMADILHA INSTITUCIONAL
    # =========================================================================
    if maxima > 0 and preco >= maxima - 1.0 and rejeicao_baixa and vies_macro == "vendedor":
        return {
            "tipo": "venda",
            "estrategia": "Rompimento Falso de Topo (Armadilha Institucional)",
            "descricao": "🔴 Falso rompimento de máxima detectado contra o fluxo comprador. Armadilha armada para venda!",
        }

    if minima > 0 and preco <= minima + 1.0 and rejeicao_alta and vies_macro == "comprador":
        return {
            "tipo": "compra",
            "estrategia": "Rompimento Falso de Fundo (Armadilha Institucional)",
            "descricao": "🟢 Falso rompimento de mínima detectado com rejeição de fundo. Armadilha armada para compra!",
        }

    return sinal_operacional


def calcular_varal_contratos_por_nivel(dados_tela, contexto, fechamento_ant=None, contratos_totais=5):
    """
    Calcula a distribuição técnica de contratos (varal de ordens) baseada
    nas zonas de liquidez, Fibonacci e distância das médias — evita ficar
    'preso no varal' sem planejamento técnico.

    Retorna: {status, direcao, contratos_totais, niveis[], mensagem}
    Cada nível: {nivel, preco, contratos, tipo, referencia}
    """
    preco = num(dados_tela.get("preco_atual", 0))
    vwap = num(dados_tela.get("vwap", 0))
    acao = contexto.get("acao_objetiva", "espera")
    est = contexto.get("estrategia", "Agressividade Média")
    pe = ESTRATEGIAS.get(est, ESTRATEGIAS["Agressividade Média"])

    if preco <= 0 or acao == "espera":
        return {"status": "inativo", "mensagem": "Aguardando gatilho para armar o varal de contratos.", "niveis": []}

    # Fibonacci do dia anterior (zonas fortes de reforço)
    fib = (fechamento_ant or {}).get("fibonacci_diario", {}) if fechamento_ant else {}
    n382 = num(fib.get("nivel_382", 0))
    n50 = num(fib.get("nivel_50", 0))
    n618 = num(fib.get("nivel_618", 0))

    # Espaçamento base entre níveis
    passo_pts = 3.5
    stop_defesa = pe["stop_pts"]

    # Distribuição inteligente: 50% entrada base + 30% reforço + 20% reserva
    lote_base = max(1, int(round(contratos_totais * 0.5)))
    lote_reforco = max(1, int(round(contratos_totais * 0.3)))
    lote_reserva = max(1, contratos_totais - lote_base - lote_reforco)

    niveis_varal = []

    if acao == "compra":
        p1 = preco
        # Reforço 1: procurar fib mais próximo abaixo do preço, se houver
        candidatos = [n for n in [n382, n50, n618] if n > 0 and n < preco and (preco - n) <= 12]
        p2 = max(candidatos) if candidatos else round(preco - passo_pts, 2)
        # Reforço 2: um passo abaixo do reforço 1
        p3 = round(p2 - passo_pts, 2)
        p_stop = round(min(p1, p2, p3) - stop_defesa, 2)
        ref2 = f"Fibonacci {p2:.2f}" if candidatos else "Suporte técnico"

        niveis_varal = [
            {"nivel": "1º Entrada Base", "preco": round(p1, 2), "contratos": lote_base,
             "tipo": "Compra Imediata", "referencia": "Preço atual"},
            {"nivel": "2º Reforço Técnico", "preco": p2, "contratos": lote_reforco,
             "tipo": "Ordem Pendente Compra", "referencia": ref2},
            {"nivel": "3º Reforço Final", "preco": p3, "contratos": lote_reserva,
             "tipo": "Ordem Pendente Compra", "referencia": "Zona de exaustão"},
            {"nivel": "🛡️ Stop Global", "preco": p_stop, "contratos": contratos_totais,
             "tipo": "Stop Loss Global", "referencia": f"-{stop_defesa} pts do último reforço"},
        ]

    elif acao == "venda":
        p1 = preco
        candidatos = [n for n in [n382, n50, n618] if n > 0 and n > preco and (n - preco) <= 12]
        p2 = min(candidatos) if candidatos else round(preco + passo_pts, 2)
        p3 = round(p2 + passo_pts, 2)
        p_stop = round(max(p1, p2, p3) + stop_defesa, 2)
        ref2 = f"Fibonacci {p2:.2f}" if candidatos else "Resistência técnica"

        niveis_varal = [
            {"nivel": "1º Entrada Base", "preco": round(p1, 2), "contratos": lote_base,
             "tipo": "Venda Imediata", "referencia": "Preço atual"},
            {"nivel": "2º Reforço Técnico", "preco": p2, "contratos": lote_reforco,
             "tipo": "Ordem Pendente Venda", "referencia": ref2},
            {"nivel": "3º Reforço Final", "preco": p3, "contratos": lote_reserva,
             "tipo": "Ordem Pendente Venda", "referencia": "Zona de exaustão"},
            {"nivel": "🛡️ Stop Global", "preco": p_stop, "contratos": contratos_totais,
             "tipo": "Stop Loss Global", "referencia": f"+{stop_defesa} pts do último reforço"},
        ]

    # Cálculo do preço médio caso todos os reforços sejam executados
    if niveis_varal:
        pm = sum(n["preco"] * n["contratos"] for n in niveis_varal[:3]) / max(1, sum(n["contratos"] for n in niveis_varal[:3]))
    else:
        pm = preco

    return {
        "status": "armado",
        "direcao": acao.upper(),
        "contratos_totais": contratos_totais,
        "preco_medio_potencial": round(pm, 2),
        "niveis": niveis_varal,
        "mensagem": f"Varal armado para {acao.upper()} — {contratos_totais} contratos escalonados em {len(niveis_varal)-1} níveis + stop global."
    }


class AutoProInstitutionalEngine:
    """
    Sistema Unificado de Alta Probabilidade e Alerta Preditivo para o AutoPro.
    Combina análise de exaustão, fluxo de agressão (Times & Trades), tendência e travas de segurança.
    """
    def __init__(self, limiar_alerta=75, score_minimo=4):
        self.limiar_alerta = limiar_alerta
        self.score_minimo = score_minimo

    def processar_mercado(self, dados_mercado):
        """
        Processa os dados em tempo real e retorna se o sinal está aprovado,
        bloqueado ou se disparou um alerta preditivo de alta/baixa.

        dados_mercado deve conter:
        - regime_tendencia: 'trend_up' ou 'trend_down'
        - saldo_agressao_pct: % do Times & Trades (ex: 57)
        - score_tecnico: pontuação interna (ex: 4)
        - preco_atual: preço atual
        - minima_dia / maxima_dia: extremidades da sessão
        - padrao_candle: 'marubozu_alta', 'marubozu_baixa', 'doji', 'nenhum'
        - rompimento_max_min: True/False
        - volume_forte: True/False
        """
        regime = dados_mercado.get("regime_tendencia")
        agressao = dados_mercado.get("saldo_agressao_pct", 50.0)
        score = dados_mercado.get("score_tecnico", 0)
        preco = dados_mercado.get("preco_atual")
        minima = dados_mercado.get("minima_dia")
        maxima = dados_mercado.get("maxima_dia")
        candle = dados_mercado.get("padrao_candle", "nenhum")
        rompimento = dados_mercado.get("rompimento_max_min", False)
        volume_forte = dados_mercado.get("volume_forte", False)

        # --- 1. TRAVA DE SEGURANÇA: EXTREMIDADES (EXAUSTÃO) ---
        if preco is not None and minima is not None and maxima is not None:
            if abs(preco - minima) <= 1.0 or abs(preco - maxima) <= 1.0:
                return {
                    "status": "ESPERA",
                    "direcao": "NEUTRO",
                    "motivo": "Preço colado na extremidade (Exaustão). Aguardar repique ou pullback."
                }

        # --- 2. CÁLCULO DE PROBABILIDADE PREDITIVA ---
        prob_alta = 0
        prob_baixa = 0
        motivos_alta = []
        motivos_baixa = []

        if agressao >= 55:
            prob_alta += 30
            motivos_alta.append("Agressão compradora dominante")
        if rompimento and candle != "marubozu_baixa":
            prob_alta += 40
            motivos_alta.append("Rompimento estrutural de alta")
        if volume_forte:
            prob_alta += 30
            motivos_alta.append("Volume institucional comprador")

        if agressao <= 45:
            prob_baixa += 30
            motivos_baixa.append("Agressão vendedora dominante")
        if rompimento and candle != "marubozu_alta":
            prob_baixa += 40
            motivos_baixa.append("Rompimento estrutural de baixa")
        if volume_forte:
            prob_baixa += 30
            motivos_baixa.append("Volume institucional vendedor")

        # --- 3. VALIDAÇÃO DE CONFLUÊNCIA & BLINDAGEM CONTRA SINAIS INVERTIDOS ---

        # Tentativa de Alerta/Disparo para ALTA
        if prob_alta >= self.limiar_alerta:
            if regime == "trend_down" or agressao < 45.0:
                return {
                    "status": "BLOQUEADO_CONTRATENDENCIA",
                    "direcao": "NEUTRO",
                    "motivo": "Alerta de alta gerado, mas bloqueado por conflito com tendência de baixa ou fluxo vendedor."
                }
            if score < self.score_minimo:
                return {
                    "status": "AGUARDANDO_SCORE",
                    "direcao": "NEUTRO",
                    "motivo": "Alta probabilidade detectada, aguardando score técnico mínimo."
                }
            return {
                "status": "DISPARO_AUTORIZADO",
                "direcao": "COMPRA",
                "probabilidade": f"{prob_alta}%",
                "fatores": motivos_alta,
                "motivo": "🚀 ALERTA MÁXIMO DE ALTA: Fluxo, tendência e rompimento perfeitamente alinhados."
            }

        # Tentativa de Alerta/Disparo para BAIXA
        if prob_baixa >= self.limiar_alerta:
            if regime == "trend_up" or agressao > 55.0:
                return {
                    "status": "BLOQUEADO_CONTRATENDENCIA",
                    "direcao": "NEUTRO",
                    "motivo": "Alerta de baixa gerado, mas bloqueado por conflito com tendência de alta ou fluxo comprador."
                }
            if score < self.score_minimo:
                return {
                    "status": "AGUARDANDO_SCORE",
                    "direcao": "NEUTRO",
                    "motivo": "Alta probabilidade detectada, aguardando score técnico mínimo."
                }
            return {
                "status": "DISPARO_AUTORIZADO",
                "direcao": "VENDA",
                "probabilidade": f"{prob_baixa}%",
                "fatores": motivos_baixa,
                "motivo": "⚠️ ALERTA MÁXIMO DE BAIXA: Fluxo, tendência e rompimento perfeitamente alinhados."
            }

        # Se não atingir o limiar de alta probabilidade
        return {
            "status": "NEUTRO",
            "direcao": "NEUTRO",
            "motivo": "Mercado sem confluência estatística suficiente (Ficar de fora / Aguardar)."
        }


# Instância global do motor institucional
INSTITUTIONAL_ENGINE = AutoProInstitutionalEngine(limiar_alerta=75, score_minimo=SCORE_MINIMO_ABSOLUTO)


class AutoProTradingDecisionEngine:
    """
    Motor de Decisão aprimorado para o AutoPro incorporando:
    1. Ponderação Dinâmica de Liquidez (Book)
    2. Filtro de Confluência de Contexto (Contratendência)
    3. Tratamento de Exaustão e Zonas de Rejeição
    """
    def __init__(self, agressividade_base="Média"):
        self.agressividade_base = agressividade_base

    def calcular_score_ponderado(self, score_atual, distancia_ofertante, saldo_agressao_pct, regime_tendencia, acao_pretendida):
        score_ajustado = score_atual

        # 2. Filtro de Confluência de Contexto (Penalização severa por operar contra a tendência)
        if regime_tendencia == "trend_down" and acao_pretendida == "COMPRA":
            score_ajustado -= 2
        elif regime_tendencia == "trend_up" and acao_pretendida == "VENDA":
            score_ajustado -= 2

        # 1. Ponderação Dinâmica de Liquidez (Penaliza se o grande lote estiver muito distante)
        # Janela ampliada em 15% (15,0 -> 17,25 pts): a régua anterior punia
        # alvos parciais válidos em volatilidade moderada.
        if distancia_ofertante > DISTANCIA_OFERTANTE_TOLERADA:
            score_ajustado -= 1

        # Alinhamento com o Fluxo de Agressão (Times & Trades)
        # Alinhado ao filtro de fluxo: neutro tambem perde ponto, nao so contrario.
        if acao_pretendida == "COMPRA" and saldo_agressao_pct < SALDO_AGRESSAO_MINIMO:
            score_ajustado -= 1
        elif acao_pretendida == "VENDA" and saldo_agressao_pct > (100.0 - SALDO_AGRESSAO_MINIMO):
            score_ajustado -= 1

        return max(0, score_ajustado)

    def avaliar_gatilho(self, dados_mercado):
        preco_atual = dados_mercado.get("preco_atual", 0) or 0
        minima_dia = dados_mercado.get("minima_dia", 0) or 0
        maxima_dia = dados_mercado.get("maxima_dia", 0) or 0

        if preco_atual <= 0 or minima_dia <= 0 or maxima_dia <= 0:
            return {"status": "APROVADO", "motivo": "Dados de extremos insuficientes — engine libera."}

        distancia_minima = abs(preco_atual - minima_dia)
        distancia_maxima = abs(preco_atual - maxima_dia)

        # 3. Tratamento de Exaustão (Converte gatilho em ESPERA nas extremidades exatas)
        if distancia_minima == 0.0 or distancia_maxima == 0.0:
            return {
                "status": "ESPERA",
                "motivo": "Exaustão detectada na extremidade. Aguardar repique ou confirmação de agressão."
            }

        return {"status": "APROVADO", "motivo": "Estrutura de preço e fluxo alinhados."}


# Instância global do motor (usada nos gatilhos)
DECISION_ENGINE = AutoProTradingDecisionEngine(agressividade_base="Média")


def _calcular_saldo_agressao_pct(agentes_info):
    """Calcula % de agressão compradora a partir da leitura de agentes/T&T.
    Retorna 50.0 quando não há dados (neutro)."""
    if not agentes_info: return 50.0
    _saldo = str(agentes_info.get("saldo_agentes", "neutro")).lower()
    _pc = float(agentes_info.get("pressao_compradora", 0) or 0)
    _pv = float(agentes_info.get("pressao_vendedora", 0) or 0)
    if _pc + _pv > 0:
        return round((_pc / (_pc + _pv)) * 100, 1)
    if _saldo == "comprador": return 60.0
    if _saldo == "vendedor": return 40.0
    return 50.0


def calcular_pressao_fluxo(agentes_info, preco):
    """Indicadores ANTECIPATIVOS: medem intencao, nao preco passado.

    Preco, medias, delta e posicao no range sao todos funcoes do passado — a soma
    deles continua sendo um indicador atrasado. Agressao, desequilibrio de book e
    absorcao mudam ANTES do preco andar: sao a unica classe de entrada capaz de
    antecipar. Guarda historico proprio para medir a TENDENCIA da pressao.
    """
    r = {"desequilibrio": 0.0, "tendencia": "neutro", "delta_agressao": 0.0,
         "absorcao": "", "exaustao_fluxo": "", "valido": False,
         "qtd_bid": 0.0, "qtd_ask": 0.0, "agressao_pct": 50.0}
    ag = agentes_info or {}
    if not ag or preco <= 0:
        return r

    bid = sum(num(o.get("qtde", 0)) for o in (ag.get("ofertantes_compra") or [])[:5])
    ask = sum(num(o.get("qtde", 0)) for o in (ag.get("ofertantes_venda") or [])[:5])
    r["qtd_bid"], r["qtd_ask"] = bid, ask
    if bid + ask > 0:
        r["desequilibrio"] = round(((bid - ask) / (bid + ask)) * 100, 1)
        r["valido"] = True

    agr = _calcular_saldo_agressao_pct(ag)
    r["agressao_pct"] = agr

    hist = st.session_state.get("hist_fluxo", [])
    hist.insert(0, {"agr": agr, "des": r["desequilibrio"], "preco": preco})
    st.session_state["hist_fluxo"] = hist[:6]

    if len(hist) >= 3:
        ref = hist[min(2, len(hist) - 1)]
        d_agr = agr - float(ref.get("agr", 50.0) or 50.0)
        d_preco = preco - num(ref.get("preco", 0))
        r["delta_agressao"] = round(d_agr, 1)

        # Limiares originais (8 p.p.) quase nunca disparavam: 3 deteccoes em 82 leituras.
        if d_agr >= 4:
            r["tendencia"] = "compradora_crescente"
        elif d_agr <= -4:
            r["tendencia"] = "vendedora_crescente"

        # ABSORCAO: agressao forte de um lado e o preco NAO anda.
        # Alguem absorve passivamente — sinal classico de reversao iminente.
        # Absorcao nao teve UMA deteccao com os limiares antigos (62/38 e 1 pt).
        # 56/44 disparava em 39% das leituras — virou ruido. Absorcao real exige
        # agressao desequilibrada E o preco travado E o book contra o agressor.
        _des_now = r.get("desequilibrio", 0.0)
        if abs(d_preco) <= 1.5:
            if agr >= 60 and _des_now <= 0:
                r["absorcao"] = "venda_absorvendo_compra"
            elif agr <= 44 and _des_now >= 0:
                r["absorcao"] = "compra_absorvendo_venda"

        # EXAUSTAO DE FLUXO: preco andou, mas a agressao ja virou contra.
        if d_preco >= 2.0 and d_agr <= -3:
            r["exaustao_fluxo"] = "alta_perdendo_forca"
        elif d_preco <= -2.0 and d_agr >= 3:
            r["exaustao_fluxo"] = "baixa_perdendo_forca"

    return r


def _calcular_distancia_maior_ofertante(preco, agentes_info, acao_pretendida):
    """Distancia (em pontos) entre o preco atual e o preco do MAIOR ofertante do lado da ação.
    COMPRA olha maior ofertante de compra (bid), VENDA olha maior ofertante de venda (ask)."""
    if not agentes_info or preco <= 0: return 0.0
    if acao_pretendida == "COMPRA":
        lst = agentes_info.get("ofertantes_compra", []) or []
    else:
        lst = agentes_info.get("ofertantes_venda", []) or []
    if not lst: return 0.0
    lst_ord = sorted(lst, key=lambda x: int(x.get("qtde", 0) or 0), reverse=True)
    maior = lst_ord[0]
    pr_maior = float(maior.get("preco", 0) or 0)
    if pr_maior <= 0: return 0.0
    return round(abs(preco - pr_maior), 2)


# =========================
# ROBO PREDITIVO — PROJECAO 5/10 MIN + ROMPIMENTO DE CANDLE
# =========================
TIMEFRAME_CANDLE_MIN = 10


def _segundos_no_candle(hora_str, timeframe_min=TIMEFRAME_CANDLE_MIN):
    """Segundos ja decorridos dentro do candle em formacao."""
    s = str(hora_str or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
    if not m:
        return 0
    hh = int(m.group(1)); mm = int(m.group(2)); ss = int(m.group(3) or 0)
    return ((hh * 3600) + (mm * 60) + ss) % (timeframe_min * 60)


def _inicio_candle(hora_str, timeframe_min=TIMEFRAME_CANDLE_MIN):
    s = str(hora_str or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if not m:
        return ""
    hh = int(m.group(1)); mm = int(m.group(2))
    return f"{hh:02d}:{(mm // timeframe_min) * timeframe_min:02d}"


def registrar_candle(dados_tela, timeframe_min=TIMEFRAME_CANDLE_MIN):
    """Historico dos ultimos candles do timeframe operacional.
    Cada candle guarda abertura, maxima, minima, fechamento parcial e volume."""
    hora = str(dados_tela.get("hora_replay") or dados_tela.get("hora") or "")
    inicio = _inicio_candle(hora, timeframe_min)
    preco = num(dados_tela.get("preco_atual", 0))
    if not inicio or preco <= 0:
        return st.session_state.get("hist_candles", [])

    volume = num(dados_tela.get("volume", 0))
    seg = _segundos_no_candle(hora, timeframe_min)
    hist = st.session_state.get("hist_candles", [])

    if hist and hist[0].get("inicio") == inicio:
        c = hist[0]
        c["maxima"] = max(num(c.get("maxima", 0)), preco)
        _mn = num(c.get("minima", 0))
        c["minima"] = min(_mn, preco) if _mn > 0 else preco
        c["fechamento"] = preco
        c["volume"] = max(num(c.get("volume", 0)), volume)
        c["segundos"] = max(int(c.get("segundos", 0) or 0), seg)
        c["leituras"] = int(c.get("leituras", 1) or 1) + 1
    else:
        if hist:
            hist[0]["encerrado"] = True
        hist.insert(0, {
            "inicio": inicio, "abertura": preco, "maxima": preco, "minima": preco,
            "fechamento": preco, "volume": volume, "segundos": seg,
            "leituras": 1, "encerrado": False,
        })

    st.session_state["hist_candles"] = hist[:12]
    return st.session_state["hist_candles"]


def projetar_volume(volume_atual, segundos_decorridos, timeframe_min=TIMEFRAME_CANDLE_MIN):
    """Extrapola o volume do candle em formacao para o fechamento."""
    total = timeframe_min * 60
    seg = max(30, int(segundos_decorridos or 0))
    if volume_atual <= 0:
        return 0.0
    if seg >= total:
        return round(float(volume_atual), 2)
    return round(float(volume_atual) * (total / seg), 2)


def gatilho_rompimento_candle(dados_tela, timeframe_min=TIMEFRAME_CANDLE_MIN, fator_volume=1.2):
    """Ordem stop no rompimento do candle anterior — dispara sem esperar o fechamento.

    VENDA : o candle anterior testou o topo e o candle em formacao PERDE a minima dele
            com volume projetado alto.
    COMPRA: espelho exato (candle anterior testou o fundo e o atual supera a maxima).
    """
    vazio = {"dispara": False, "direcao": "espera", "nivel": 0.0, "motivo": "",
             "volume_projetado": 0.0, "volume_referencia": 0.0, "forca": 0,
             "nivel_stop_venda": 0.0, "nivel_stop_compra": 0.0}
    hist = st.session_state.get("hist_candles", [])
    preco = num(dados_tela.get("preco_atual", 0))
    if len(hist) < 2 or preco <= 0:
        return vazio

    atual, ant = hist[0], hist[1]
    ant_max = num(ant.get("maxima", 0)); ant_min = num(ant.get("minima", 0))
    ant_ab = num(ant.get("abertura", 0)); ant_fc = num(ant.get("fechamento", 0))
    if ant_max <= 0 or ant_min <= 0 or ant_max <= ant_min:
        return vazio

    amp = ant_max - ant_min
    max_dia = num(dados_tela.get("maxima", 0))
    min_dia = num(dados_tela.get("minima", 0))

    pavio_sup = (ant_max - max(ant_ab, ant_fc)) / amp
    fechou_baixo = ant_fc <= (ant_min + amp * 0.5)
    perto_max_dia = max_dia > 0 and (max_dia - ant_max) <= max(1.5, amp * 0.25)
    testou_topo = (pavio_sup >= 0.25 or fechou_baixo) and (perto_max_dia or pavio_sup >= 0.35)

    pavio_inf = (min(ant_ab, ant_fc) - ant_min) / amp
    fechou_alto = ant_fc >= (ant_max - amp * 0.5)
    perto_min_dia = min_dia > 0 and (ant_min - min_dia) <= max(1.5, amp * 0.25)
    testou_fundo = (pavio_inf >= 0.25 or fechou_alto) and (perto_min_dia or pavio_inf >= 0.35)

    vol_proj = projetar_volume(num(atual.get("volume", 0)), atual.get("segundos", 0), timeframe_min)
    vol_ref = num(ant.get("volume", 0))
    volume_alto = vol_ref <= 0 or vol_proj >= vol_ref * fator_volume

    base = dict(vazio)
    base["volume_projetado"] = vol_proj
    base["volume_referencia"] = vol_ref
    base["nivel_stop_venda"] = round(ant_min - 0.5, 2)
    base["nivel_stop_compra"] = round(ant_max + 0.5, 2)

    if testou_topo and preco < ant_min:
        forca = 60 + (20 if volume_alto else 0)
        if max_dia > 0 and (max_dia - ant_max) <= 1.0: forca += 10
        if preco <= ant_min - 1.0: forca += 10
        base.update({
            "dispara": bool(volume_alto), "direcao": "venda", "nivel": round(ant_min, 2),
            "forca": min(100, forca),
            "motivo": (f"Rompimento de baixa: candle anterior testou o topo em {ant_max:.2f} e o atual "
                       f"perdeu a mínima {ant_min:.2f}. Volume projetado {vol_proj:.0f} vs {vol_ref:.0f} do anterior."),
        })
        return base

    if testou_fundo and preco > ant_max:
        forca = 60 + (20 if volume_alto else 0)
        if min_dia > 0 and (ant_min - min_dia) <= 1.0: forca += 10
        if preco >= ant_max + 1.0: forca += 10
        base.update({
            "dispara": bool(volume_alto), "direcao": "compra", "nivel": round(ant_max, 2),
            "forca": min(100, forca),
            "motivo": (f"Rompimento de alta: candle anterior testou o fundo em {ant_min:.2f} e o atual "
                       f"superou a máxima {ant_max:.2f}. Volume projetado {vol_proj:.0f} vs {vol_ref:.0f} do anterior."),
        })
        return base

    if testou_topo:
        base["direcao"] = "venda_pendente"
        base["motivo"] = f"Ordem stop de venda armada em {ant_min:.2f} (mínima do candle que testou o topo {ant_max:.2f})."
    elif testou_fundo:
        base["direcao"] = "compra_pendente"
        base["motivo"] = f"Ordem stop de compra armada em {ant_max:.2f} (máxima do candle que testou o fundo {ant_min:.2f})."
    return base


def validar_integridade_book(agentes_info, preco, tolerancia_pts=10.0):
    """Descarta a leitura de fluxo quando o book esta congelado ou fora de preco."""
    res = {"valido": True, "motivo": "", "congelado": False, "fora_de_preco": False}
    ag = agentes_info or {}
    if preco <= 0:
        return res

    precos = []
    for lado in ("ofertantes_compra", "ofertantes_venda"):
        for o in (ag.get(lado) or [])[:5]:
            p = num(o.get("preco", 0))
            if p > 0:
                precos.append(p)
    if precos:
        dist = min(abs(preco - p) for p in precos)
        if dist > tolerancia_pts:
            res.update({"valido": False, "fora_de_preco": True,
                        "motivo": f"Book a {dist:.1f} pts do preço negociado — leitura de fluxo descartada."})
            return res

    tem_dados = bool((ag.get("ofertantes_compra") or []) or (ag.get("ofertantes_venda") or []))
    assinatura = json.dumps({
        "c": [[o.get("preco"), o.get("qtde")] for o in (ag.get("ofertantes_compra") or [])[:3]],
        "v": [[o.get("preco"), o.get("qtde")] for o in (ag.get("ofertantes_venda") or [])[:3]],
    }, ensure_ascii=False, sort_keys=True, default=str)

    hist_sig = st.session_state.get("hist_assinatura_book", [])
    repeticoes = sum(1 for s in hist_sig[:3] if s == assinatura)
    hist_sig.insert(0, assinatura)
    st.session_state["hist_assinatura_book"] = hist_sig[:6]

    if tem_dados and repeticoes >= 2:
        res.update({"valido": False, "congelado": True,
                    "motivo": "Book idêntico em 3 leituras seguidas — fluxo congelado, viés descartado."})
    return res


def calcular_velocidade_real(dados_tela, momentum_info, timeframe_min=TIMEFRAME_CANDLE_MIN):
    """Velocidade em pts/min medida nos candles reais.

    Retorna (velocidade, valida). valida=False significa "sem dado suficiente",
    que e MUITO diferente de "mercado parado". Confundir os dois fazia o robo
    tratar toda alta como exaustao.
    """
    preco = num(dados_tela.get("preco_atual", 0))
    hc = st.session_state.get("hist_candles", [])

    if preco > 0 and len(hc) >= 2:
        for i in range(1, min(4, len(hc))):
            ref = num(hc[i].get("fechamento", 0))
            if ref > 0:
                minutos = (i * timeframe_min) + (num(hc[0].get("segundos", 0)) / 60.0)
                if minutos >= 1.0:
                    return round((preco - ref) / minutos, 3), True

    mom = momentum_info or {}
    d3 = float(mom.get("delta_3", 0) or 0)
    d1 = float(mom.get("delta_preco", 0) or 0)
    if d3 != 0:
        return round(d3 / 15.0, 3), True
    if d1 != 0:
        return round(d1 / 5.0, 3), True

    _mm_txt = str(mom.get("momentum", "") or "")
    if _mm_txt in ("alta_forte", "alta", "baixa", "baixa_forte"):
        _mapa = {"alta_forte": 0.6, "alta": 0.25, "baixa": -0.25, "baixa_forte": -0.6}
        return _mapa[_mm_txt], True

    return 0.0, False


def avaliar_lotes_institucionais(agentes_info, preco, limite=1000):
    """Grandes players: lotes >= 1000 contratos definem onde o dinheiro grande está.

    Defesa = parede do lado do bid abaixo do preco (sustenta).
    Teto   = parede do lado do ask acima do preco (trava).
    """
    r = {"defesa": 0.0, "teto": 0.0, "qtd_defesa": 0, "qtd_teto": 0,
         "vies": "neutro", "forca": 0, "resumo": ""}
    ag = agentes_info or {}
    if preco <= 0:
        return r

    _bids = [(num(o.get("preco", 0)), num(o.get("qtde", 0)), str(o.get("agente", "BOOK")))
             for o in (ag.get("ofertantes_compra") or []) if num(o.get("qtde", 0)) >= limite]
    _asks = [(num(o.get("preco", 0)), num(o.get("qtde", 0)), str(o.get("agente", "BOOK")))
             for o in (ag.get("ofertantes_venda") or []) if num(o.get("qtde", 0)) >= limite]

    _bids = [b for b in _bids if 0 < b[0] <= preco + 2]
    _asks = [a for a in _asks if a[0] >= preco - 2]

    if _bids:
        _b = max(_bids, key=lambda x: x[1])
        r["defesa"], r["qtd_defesa"] = _b[0], int(_b[1])
    if _asks:
        _a = max(_asks, key=lambda x: x[1])
        r["teto"], r["qtd_teto"] = _a[0], int(_a[1])

    _qd, _qt = r["qtd_defesa"], r["qtd_teto"]
    if _qd or _qt:
        _tot = _qd + _qt
        _dif = (_qd - _qt) / _tot if _tot else 0
        if _dif >= 0.25:
            r["vies"] = "compra"
        elif _dif <= -0.25:
            r["vies"] = "venda"
        r["forca"] = int(min(100, abs(_dif) * 100))
        _p = []
        if _qd: _p.append(f"defesa de {_qd} em {r['defesa']:.2f}")
        if _qt: _p.append(f"teto de {_qt} em {r['teto']:.2f}")
        r["resumo"] = "Grandes lotes: " + " · ".join(_p)
    return r


def prever_movimento(dados_tela, momentum_info, zonas_info, rompimento=None,
                     velocidade_real=None, velocidade_valida=None, fluxo=None, lotes=None,
                     timeframe_min=TIMEFRAME_CANDLE_MIN):
    """Projeta a tendencia dos proximos 5 e 10 minutos.

    Em vez de descrever o passado, mede velocidade, aceleracao, espaco livre ate a
    proxima zona forte e rompimento de candle para estimar onde o preco deve estar.
    """
    preco = num(dados_tela.get("preco_atual", 0))
    r = {"direcao_prevista": "indefinido", "prob_alta_5": 50, "prob_baixa_5": 50,
         "prob_alta_10": 50, "prob_baixa_10": 50, "projecao_5": preco, "projecao_10": preco,
         "velocidade_pts_min": 0.0, "velocidade_valida": False, "aceleracao": 0.0, "confianca": 0,
         "fatores": [], "espaco_alta": 0.0, "espaco_baixa": 0.0}
    if preco <= 0:
        return r

    hist = st.session_state.get("hist_leituras", [])
    mom = momentum_info or {}
    delta_1 = float(mom.get("delta_preco", 0) or 0)
    delta_3 = float(mom.get("delta_3", 0) or 0)
    pos_range = float(mom.get("pos_range", 50) or 50)
    inc9 = float(mom.get("inclinacao_mm9", 0) or 0)
    inc20 = float(mom.get("inclinacao_mm20", 0) or 0)

    if velocidade_real is None:
        velocidade, vel_valida = calcular_velocidade_real(dados_tela, mom, timeframe_min)
    else:
        velocidade = float(velocidade_real)
        vel_valida = bool(velocidade_valida) if velocidade_valida is not None else True
    aceleracao = round(delta_1 - (delta_3 / 3.0), 3)
    r["velocidade_pts_min"] = velocidade
    r["velocidade_valida"] = vel_valida
    r["aceleracao"] = aceleracao

    espaco_alta, espaco_baixa = 99.0, 99.0
    for z in ((zonas_info or {}).get("zonas", []) or []):
        if int(z.get("forca", 0) or 0) < 24:
            continue
        pm = float(z.get("preco_medio", 0) or 0)
        if pm <= 0:
            continue
        if pm > preco:
            espaco_alta = min(espaco_alta, pm - preco)
        elif pm < preco:
            espaco_baixa = min(espaco_baixa, preco - pm)
    r["espaco_alta"] = round(espaco_alta, 2) if espaco_alta < 99 else 0.0
    r["espaco_baixa"] = round(espaco_baixa, 2) if espaco_baixa < 99 else 0.0

    pa, pb, fatores = 0, 0, []

    # Velocidade e um dado ATRASADO: peso reduzido de 22 para 12.
    # Continuacao de movimento medida no proprio preco nao antecipa nada.
    # Previsao medida: 85% de coincidencia com o passado contra 37% de acerto no
    # futuro. Peso do preco cai de 12 para 8; o fluxo passa a dominar.
    if velocidade > 0.15:
        pa += 8; fatores.append(f"Velocidade de alta {velocidade:+.2f} pts/min")
    elif velocidade < -0.15:
        pb += 8; fatores.append(f"Velocidade de baixa {velocidade:+.2f} pts/min")

    # ---- FLUXO: os unicos fatores realmente antecipativos ----
    _fx = fluxo or {}
    if _fx.get("valido"):
        # ABSORCAO: 77,8% de acerto medido contra 42,9% sem ela. Peso maximo.
        _abs_top = str(_fx.get("absorcao", ""))
        if _abs_top == "venda_absorvendo_compra":
            pb += 34
        elif _abs_top == "compra_absorvendo_venda":
            pa += 34
        _des = float(_fx.get("desequilibrio", 0) or 0)
        if _des >= 20:
            pa += 20; fatores.append(f"Book desequilibrado para compra ({_des:+.0f}%)")
        elif _des <= -20:
            pb += 20; fatores.append(f"Book desequilibrado para venda ({_des:+.0f}%)")

        _tend = str(_fx.get("tendencia", ""))
        _dagr = float(_fx.get("delta_agressao", 0) or 0)
        if _tend == "compradora_crescente":
            pa += 24; fatores.append(f"Agressão compradora crescendo ({_dagr:+.0f} p.p.)")
        elif _tend == "vendedora_crescente":
            pb += 24; fatores.append(f"Agressão vendedora crescendo ({_dagr:+.0f} p.p.)")

        # Absorcao e exaustao de fluxo apontam para a REVERSAO — peso alto.
        _abs = str(_fx.get("absorcao", ""))
        if _abs == "venda_absorvendo_compra":
            pb += 26; fatores.append("Absorção: compra agredindo sem o preço subir")
        elif _abs == "compra_absorvendo_venda":
            pa += 26; fatores.append("Absorção: venda agredindo sem o preço cair")

        _exf = str(_fx.get("exaustao_fluxo", ""))
        if _exf == "alta_perdendo_forca":
            pb += 22; fatores.append("Alta perdendo força: agressão já virou vendedora")
        elif _exf == "baixa_perdendo_forca":
            pa += 22; fatores.append("Baixa perdendo força: agressão já virou compradora")
    else:
        fatores.append("Sem leitura de fluxo — previsão apenas por preço (atrasada)")

    # ---- GRANDES LOTES: onde o dinheiro institucional está posicionado ----
    _lt = lotes or {}
    if _lt.get("vies") == "compra" and _lt.get("forca", 0) >= 25:
        pa += 18; fatores.append(_lt.get("resumo", "Grandes lotes sustentando a compra"))
    elif _lt.get("vies") == "venda" and _lt.get("forca", 0) >= 25:
        pb += 18; fatores.append(_lt.get("resumo", "Grandes lotes travando a alta"))

    if aceleracao > 0.5:
        pa += 12; fatores.append("Movimento acelerando para cima")
    elif aceleracao < -0.5:
        pb += 12; fatores.append("Movimento acelerando para baixo")

    if inc9 > 0 and inc20 > 0:
        pa += 8; fatores.append("MM9 e MM20 inclinadas para cima")
    elif inc9 < 0 and inc20 < 0:
        pb += 8; fatores.append("MM9 e MM20 inclinadas para baixo")

    # Espaco livre so vale como fator na direcao em que o preco esta indo.
    # Zona proxima acima nao e sinal de queda: num rompimento ela e alvo, nao barreira.
    if espaco_alta < 99 and espaco_baixa < 99:
        _sobe = velocidade > 0.05
        _desce = velocidade < -0.05
        if espaco_alta > espaco_baixa * 1.5 and not _desce:
            pa += 14; fatores.append(f"Espaço livre de {espaco_alta:.1f} pts acima até a próxima zona")
        elif espaco_baixa > espaco_alta * 1.5 and not _sobe:
            pb += 14; fatores.append(f"Espaço livre de {espaco_baixa:.1f} pts abaixo até a próxima zona")

    # Extremo do range: continuacao quando ha velocidade, exaustao apenas quando
    # a velocidade foi REALMENTE medida e esta perto de zero.
    _max_dia = num(dados_tela.get("maxima", 0))
    _min_dia = num(dados_tela.get("minima", 0))
    _rompendo_topo = _max_dia > 0 and preco >= _max_dia - 0.5
    _rompendo_fundo = _min_dia > 0 and preco <= _min_dia + 0.5

    if _rompendo_topo and velocidade > 0.10:
        pa += 22; fatores.append(f"Rompendo a máxima do dia ({_max_dia:.2f}) com velocidade")
    elif _rompendo_fundo and velocidade < -0.10:
        pb += 22; fatores.append(f"Rompendo a mínima do dia ({_min_dia:.2f}) com velocidade")
    elif vel_valida and pos_range >= 85 and abs(velocidade) <= 0.05:
        pb += 16; fatores.append("Preço no topo do range e velocidade zerada")
    elif vel_valida and pos_range <= 15 and abs(velocidade) <= 0.05:
        pa += 16; fatores.append("Preço no fundo do range e velocidade zerada")

    if not vel_valida:
        fatores.append("Sem histórico suficiente para medir velocidade")

    rp = rompimento or {}
    if rp.get("dispara") and rp.get("direcao") == "venda":
        pb += 26; fatores.append("Rompimento da mínima do candle anterior confirmado")
    elif rp.get("dispara") and rp.get("direcao") == "compra":
        pa += 26; fatores.append("Rompimento da máxima do candle anterior confirmado")
    elif rp.get("direcao") == "venda_pendente":
        pb += 8; fatores.append(f"Stop de venda armado em {num(rp.get('nivel_stop_venda', 0)):.2f}")
    elif rp.get("direcao") == "compra_pendente":
        pa += 8; fatores.append(f"Stop de compra armado em {num(rp.get('nivel_stop_compra', 0)):.2f}")

    total = pa + pb
    if total <= 0:
        return r

    p10 = max(5, min(95, int(round(50 + ((pa - pb) / max(30, total)) * 45))))
    p5 = int(round(50 + (p10 - 50) * 0.75))
    r["prob_alta_10"] = p10; r["prob_baixa_10"] = 100 - p10
    r["prob_alta_5"] = p5;   r["prob_baixa_5"] = 100 - p5

    proj5 = preco + velocidade * 5
    proj10 = preco + velocidade * 10
    if velocidade > 0 and espaco_alta < 99:
        proj5 = min(proj5, preco + espaco_alta); proj10 = min(proj10, preco + espaco_alta)
    if velocidade < 0 and espaco_baixa < 99:
        proj5 = max(proj5, preco - espaco_baixa); proj10 = max(proj10, preco - espaco_baixa)
    r["projecao_5"] = round(proj5, 2)
    r["projecao_10"] = round(proj10, 2)

    if p10 >= 62:
        r["direcao_prevista"] = "compra"
    elif p10 <= 38:
        r["direcao_prevista"] = "venda"
    r["confianca"] = int(min(100, abs(p10 - 50) * 2))
    r["fatores"] = fatores[:5]
    return r


def classificar_contexto(dados_tela, fechamento_ant=None, ignorar_macro=False):
    preco = num(dados_tela.get("preco_atual"))
    vwap = num(dados_tela.get("vwap"))
    ajuste = num(dados_tela.get("ajuste"))
    # Ajuste ausente na tela: usa o do fechamento anterior. Sem ele o primeiro
    # toque do dia no Ajuste (setup de scalp) nunca era detectado.
    _ajuste_origem = "tela" if ajuste > 0 else ""
    if ajuste <= 0:
        try:
            _fa = fechamento_ant or ler_fechamento_anterior() or {}
            _aj_ant = num(_fa.get("ajuste", 0)) or num(_fa.get("preco", 0))
            if _aj_ant > 0:
                ajuste = _aj_ant
                _ajuste_origem = "fechamento_anterior"
                dados_tela["ajuste"] = _aj_ant
        except Exception:
            pass
    mm9 = num(dados_tela.get("mm9"))
    mm20 = num(dados_tela.get("mm20"))
    mm50 = num(dados_tela.get("mm50"))
    mm200 = num(dados_tela.get("mm200"))
    hora = dados_tela.get("hora_replay") or dados_tela.get("hora") or ""

    vies_ant = "indefinido"
    if not ignorar_macro and fechamento_ant:
        vies_ant = fechamento_ant.get("vies", "indefinido")

    val = validar_leitura(dados_tela)
    if not val["consistente"]:
        return {
            "estrategia": "Conservador", "regime": "inconsistente", "acao_objetiva": "espera",
            "vies": "inconsistente", "motivo_objetivo": f"Espera obrigatoria: {val['erros']}",
            "resumo_objetivo": str(val["erros"]), "score": 0, "score_minimo_usado": 0,
            "vies_anterior": vies_ant, "validacao": val, "limiar": 0,
            "dist_vwap": 0, "dist_ajuste": 0, "dist_mm9": 0, "dist_mm20": 0, "dist_mm50": 0, "dist_mm200": 0,
        }

    # ---- MOMENTUM: direcao real do movimento (medias sao atrasadas) ----
    registrar_leitura_historico(dados_tela)
    mom = calcular_momentum(dados_tela)

    # ---- ROBO PREDITIVO: candles do timeframe + ordem stop de rompimento ----
    registrar_candle(dados_tela)
    rompimento = gatilho_rompimento_candle(dados_tela)
    vel_real, vel_valida_ctx = calcular_velocidade_real(dados_tela, mom)
    fluxo_info = calcular_pressao_fluxo(st.session_state.get("ultimos_agentes", {}), preco)
    abertura_info = avaliar_janela_abertura(dados_tela, fechamento_ant)
    lotes_info = avaliar_lotes_institucionais(st.session_state.get("ultimos_agentes", {}), preco)

    # ---- PMI dos EUA: vies macro para o Mini Dolar ----
    if ignorar_macro:
        _macro_pmi = {}
    elif st.session_state.get("modo_replay_ativo"):
        # No replay a coleta ao vivo nao vale: busca o macro da DATA do replay
        # nas fontes com historico (BCB, FRED, FMP). O que nao vier fica
        # marcado como indisponivel e nao pontua.
        _macro_pmi = macro_para_replay(
            st.session_state.get("data_replay")
            or str((dados_tela or {}).get("data", ""))[:10])
    else:
        # A coleta web tem relogio proprio no topo do app; aqui apenas LE o
        # arquivo ja gravado. Buscar na web dentro da analise travava o ciclo.
        _macro_pmi = ler_dados_macro()
    pmi_info = peso_pmi_eua(_macro_pmi)

    regime = classificar_regime(preco, vwap, ajuste, mm9, mm20, mm50, mm200, momentum=mom)
    est_auto = estrategia_por_horario(hora, regime, vies_ant)
    p = ESTRATEGIAS[est_auto]

    # ---------------- Detecção de direção com CONFLITO ----------------
    # Sinais separados de curto (MM9/VWAP) e médio (MM20/MM50)
    sinais_compra = 0
    sinais_venda = 0
    if mm9 > 0:
        if preco >= mm9: sinais_compra += 1
        else: sinais_venda += 1
    if vwap > 0:
        if preco >= vwap: sinais_compra += 1
        else: sinais_venda += 1
    if mm20 > 0:
        if preco >= mm20: sinais_compra += 1
        else: sinais_venda += 1
    if mm50 > 0:
        if preco >= mm50: sinais_compra += 1
        else: sinais_venda += 1

    conflito = False
    # CONFLITO reforçado: só quando MM9, MM20 E VWAP apontam para lados divergentes
    # (3 sinais divergentes minimo). Evita bloquear em consolidação normal.
    _sinais_divergentes = 0
    if mm9 > 0 and mm20 > 0 and ((preco >= mm9) != (preco >= mm20)): _sinais_divergentes += 1
    if mm9 > 0 and vwap > 0 and ((preco >= mm9) != (preco >= vwap)): _sinais_divergentes += 1
    if mm20 > 0 and vwap > 0 and ((preco >= mm20) != (preco >= vwap)): _sinais_divergentes += 1
    if _sinais_divergentes >= 3:
        conflito = True

    if sinais_compra > sinais_venda:
        acao, vies = "compra", "tendência de alta"
    elif sinais_venda > sinais_compra:
        acao, vies = "venda", "tendência de baixa"
    else:
        acao, vies = "compra" if (vwap > 0 and preco >= vwap) else "venda", "empate técnico"

    # ---- CORRECAO DE DIRECAO PELO MOMENTUM ----
    # Medias moveis sao atrasadas: num repique de fundo o preco ainda esta ABAIXO
    # delas mesmo ja subindo forte. Sem isso o sistema vende no fundo (erro de 04/08).
    _mm = mom.get("momentum", "neutro")
    _pr_range = mom.get("pos_range", 50.0)
    corrigido_por_momentum = False

    # Persistência de alta/baixa: evita insistir contra o preço andando
    _delta3 = float(mom.get("delta_3", 0) or 0)
    _delta_preco = float(mom.get("delta_preco", 0) or 0)
    _acima_mm9 = mm9 > 0 and preco > mm9
    _acima_mm20 = mm20 > 0 and preco > mm20
    _abaixo_mm9 = mm9 > 0 and preco < mm9
    _abaixo_mm20 = mm20 > 0 and preco < mm20

    persistencia_alta = (_mm in ("alta", "alta_forte") and (_delta3 >= 1.5 or _delta_preco >= 1.0) and (_acima_mm9 or _acima_mm20))
    persistencia_baixa = (_mm in ("baixa", "baixa_forte") and (_delta3 <= -1.5 or _delta_preco <= -1.0) and (_abaixo_mm9 or _abaixo_mm20))

    # ---- AJUSTE 1: falha de recuperacao do ajuste ----
    # Abriu abaixo do ajuste, testou duas vezes e rejeitou = venda antes do regime virar.
    _abertura_dia = num(dados_tela.get("abertura", 0))
    falha_recuperacao_ajuste = False
    rejeicao_ajuste_pts = 0.0
    if ajuste > 0 and preco > 0:
        _hc = st.session_state.get("hist_candles", [])
        _testes_topo = sum(1 for c in _hc[:4]
                           if num(c.get("maxima", 0)) >= ajuste - 1.0 and num(c.get("fechamento", 0)) < ajuste)
        _testes_fundo = sum(1 for c in _hc[:4]
                            if 0 < num(c.get("minima", 0)) <= ajuste + 1.0 and num(c.get("fechamento", 0)) > ajuste)
        if 0 < _abertura_dia < ajuste and preco < ajuste and _testes_topo >= 2:
            falha_recuperacao_ajuste = True
            rejeicao_ajuste_pts = round(ajuste - preco, 2)
            if acao == "compra":
                acao = "venda"
                vies = f"falha de recuperação do ajuste {ajuste:.2f} ({_testes_topo} rejeições)"
        elif _abertura_dia > ajuste > 0 and preco > ajuste and _testes_fundo >= 2:
            falha_recuperacao_ajuste = True
            rejeicao_ajuste_pts = round(preco - ajuste, 2)
            if acao == "venda":
                acao = "compra"
                vies = f"defesa do ajuste {ajuste:.2f} ({_testes_fundo} rejeições)"

    if _mm in ("alta_forte", "alta") and acao == "venda":
        # so corrige se o movimento for consistente (nao ruido de 1 leitura)
        if mom.get("delta_3", 0) >= 1.5 or _mm == "alta_forte":
            acao = "compra"
            vies = f"corrigido por momentum de {_mm} (+{mom.get('delta_3',0):.1f} pts em 3 leituras)"
            corrigido_por_momentum = True
    elif _mm in ("baixa_forte", "baixa") and acao == "compra":
        if mom.get("delta_3", 0) <= -1.5 or _mm == "baixa_forte":
            acao = "venda"
            vies = f"corrigido por momentum de {_mm} ({mom.get('delta_3',0):.1f} pts em 3 leituras)"
            corrigido_por_momentum = True

    # Repique de fundo: preco no terco inferior subindo = compra, nunca venda
    if _pr_range <= 30 and _mm in ("alta", "alta_forte") and acao == "venda":
        acao = "compra"
        vies = f"repique de fundo (preco a {_pr_range:.0f}% do range, subindo)"
        corrigido_por_momentum = True
    # Rejeicao de topo: preco no terco superior caindo = venda, nunca compra
    elif _pr_range >= 70 and _mm in ("baixa", "baixa_forte") and acao == "compra":
        acao = "venda"
        vies = f"rejeicao de topo (preco a {_pr_range:.0f}% do range, caindo)"
        corrigido_por_momentum = True

    # ---------------- Padrão de candle (vindo da IA) ----------------
    padrao = str(dados_tela.get("padrao_candle","")).lower().strip()
    padroes_alta = ["engolfo_alta","pinbar_alta","martelo","estrela_da_manha","marubozu_alta","bull_engolfo"]
    padroes_baixa = ["engolfo_baixa","pinbar_baixa","estrela_da_tarde","marubozu_baixa","bear_engolfo","estrela_cadente"]
    padroes_neutros = ["doji","harami","indeciso","nenhum",""]
    padrao_confirma = (
        (acao == "compra" and padrao in padroes_alta) or
        (acao == "venda"  and padrao in padroes_baixa)
    )
    padrao_contradiz = (
        (acao == "compra" and padrao in padroes_baixa) or
        (acao == "venda"  and padrao in padroes_alta)
    )

    # ---------------- INVERSÃO POR CANDLE DE REVERSÃO FORTE ----------------
    # Um marubozu/engolfo contra a pretensão não é motivo de bloqueio:
    # é o sinal de reversão. Em vez de travar, o sistema VIRA a direção.
    padroes_fortes = [
        "marubozu_alta", "marubozu_baixa", "engolfo_alta", "engolfo_baixa",
        "bull_engolfo", "bear_engolfo", "estrela_da_manha", "estrela_da_tarde",
        "estrela_cadente", "martelo", "pinbar_alta", "pinbar_baixa",
    ]
    inverteu_por_candle = False
    if padrao_contradiz and padrao in padroes_fortes:
        acao = "venda" if acao == "compra" else "compra"
        vies = f"revertido por candle {padrao}"
        inverteu_por_candle = True
        padrao_confirma = True
        padrao_contradiz = False

    # ---------------- Volume mínimo ----------------
    volume_atual = num(dados_tela.get("volume", 0))
    # Limiar dinâmico: usa 800 como base (Mini Dólar típico), 1500 = forte
    # VOLUME_MINIMO_OK e a UNICA fonte do piso de volume: o texto do diagnostico
    # dizia ">= 800" enquanto o teste usava 300 — numeros diferentes na mesma regra.
    volume_ok = volume_atual == 0 or volume_atual >= VOLUME_MINIMO_OK   # 0 = nao capturado, nao penaliza
    volume_nao_lido = volume_atual == 0
    volume_forte = volume_atual >= 1000

    # ---------------- Suporte/Resistência dinâmicos ----------------
    # Exaustão: se preço colou na máxima/mínima do dia, bloqueia entrada a favor
    maxima_dia = num(dados_tela.get("maxima", 0))
    minima_dia = num(dados_tela.get("minima", 0))
    dist_max = (maxima_dia - preco) if maxima_dia > 0 else 999
    dist_min = (preco - minima_dia) if minima_dia > 0 else 999
    # Exaustao so vale se o momentum NAO estiver empurrando a favor da operacao.
    # Comprar colado na maxima com momentum de alta forte e rompimento, nao exaustao.
    # Momentum pode vir vazio; a velocidade medida cobre esse buraco.
    # Momentum sozinho NAO derruba a exaustao: comprar colado na maxima porque "esta subindo"
    # foi a origem das perdas. Só rompimento confirmado do candle anterior com volume libera.
    _rmp_ok = bool(rompimento.get("dispara"))
    _mom_ok_compra = _rmp_ok and rompimento.get("direcao") == "compra"
    _mom_ok_venda = _rmp_ok and rompimento.get("direcao") == "venda"

    # Zona de exaustao ESCALA com a amplitude do dia. Num pregao de 80 pts,
    # 5 pts da maxima e ruido; num de 15 pts, e o topo de verdade.
    _amp_hoje = (maxima_dia - minima_dia) if (maxima_dia > minima_dia > 0) else 0.0
    _zona_ex = max(1.5, min(6.0, _amp_hoje * 0.035)) if _amp_hoje > 0 else 5.0

    # Tendencia madura (dia amplo + preco na ponta com velocidade a favor) nao e
    # exaustao: e continuacao. Só marca exaustao se a velocidade morreu.
    _vel_morta = (not vel_valida_ctx) or abs(vel_real) <= 0.08
    _cont_compra = _amp_hoje >= 25 and vel_valida_ctx and vel_real > 0.10
    _cont_venda = _amp_hoje >= 25 and vel_valida_ctx and vel_real < -0.10

    # Exaustao deixou de bastar a proximidade do extremo: exige TAMBEM que o
    # dia tenha amplitude relevante ou que o candle confirme a virada. Colado na
    # maxima num dia de 12 pts nao e exaustao, e range estreito.
    _amp_relevante = _amp_hoje >= 12.0
    _confirma_topo = (padrao in padroes_baixa) or (regime in ("trend_down", "pullback_down"))
    _confirma_fundo = (padrao in padroes_alta) or (regime in ("trend_up", "pullback_up"))

    exaustao_topo = (maxima_dia > 0 and dist_max <= _zona_ex and acao == "compra"
                     and not _mom_ok_compra and not _cont_compra and _vel_morta
                     and (_amp_relevante or _confirma_topo))
    exaustao_fundo = (minima_dia > 0 and dist_min <= _zona_ex and acao == "venda"
                      and not _mom_ok_venda and not _cont_venda and _vel_morta
                      and (_amp_relevante or _confirma_fundo))

    # ---------------- EXAUSTÃO VIRA REVERSÃO ----------------
    # Preço colado na máxima com candle de baixa ou regime de baixa = setup de VENDA,
    # não motivo de espera. Mesma lógica invertida no fundo.
    reversao_por_exaustao = False
    if exaustao_topo and (padrao in padroes_baixa or regime in ("trend_down", "pullback_down")):
        acao = "venda"
        vies = f"reversão no topo (a {dist_max:.1f} pts da máxima {maxima_dia:.2f})"
        exaustao_topo = False
        reversao_por_exaustao = True
        padrao_confirma = padrao in padroes_baixa
        padrao_contradiz = False
    elif exaustao_fundo and (padrao in padroes_alta or regime in ("trend_up", "pullback_up")):
        acao = "compra"
        vies = f"reversão no fundo (a {dist_min:.1f} pts da mínima {minima_dia:.2f})"
        exaustao_fundo = False
        reversao_por_exaustao = True
        padrao_confirma = padrao in padroes_alta
        padrao_contradiz = False

    zonas_pf = consolidar_zonas_pontos_fortes(
        dados_tela,
        fechamento_ant=fechamento_ant,
        agentes_info=st.session_state.get("ultimos_agentes", {}),
        tolerancia=2.0,
    )
    zona_mais_proxima = zonas_pf.get("zona_mais_proxima") or {}
    dist_zona = float(zona_mais_proxima.get("distancia_preco", 999) or 999)
    lado_zona = str(zona_mais_proxima.get("lado", "neutra"))
    forca_zona = int(zona_mais_proxima.get("forca", 0) or 0)
    rotulos_zona = zona_mais_proxima.get("rotulos", []) or []

    previsao = prever_movimento(dados_tela, mom, zonas_pf, rompimento,
                                velocidade_real=vel_real, velocidade_valida=vel_valida_ctx,
                                fluxo=fluxo_info, lotes=lotes_info)
    integridade_book = validar_integridade_book(st.session_state.get("ultimos_agentes", {}), preco)

    score = calcular_score(preco, vwap, ajuste, mm9, mm20, mm50, mm200, regime, acao)

    # Bônus/penalizações
    # Momentum alinhado com a direcao vale mais que qualquer media isolada
    # Momentum FORTE a favor rendeu 40,9% e saldo de -19,2 pts: e sinal de
    # movimento esticado, nao de forca. Deixa de dar bonus e passa a penalizar.
    _vol_candle = num(dados_tela.get("volume", 0))
    if (_mm == "alta_forte" and acao == "compra") or (_mm == "baixa_forte" and acao == "venda"):
        score = max(0, score - 1)
        # Sem volume confirmando, a combinacao caiu para 33% e -17,2 pts.
        if _vol_candle <= 0:
            score = max(0, score - 2)
    elif (_mm == "alta" and acao == "compra") or (_mm == "baixa" and acao == "venda"):
        score = min(7, score + 1)
    elif (_mm in ("alta_forte","alta") and acao == "venda") or (_mm in ("baixa_forte","baixa") and acao == "compra"):
        score = max(0, score - 2)   # operando contra o momentum

    # PMI dos EUA: peso macro na direcao do dolar
    # PMI veio vazio em 100% das 608 leituras medidas: sem dado, sem peso.
    _pmi_peso = pmi_info.get("peso", 0) if pmi_info.get("pmi") else 0
    if (_pmi_peso > 0 and acao == "compra") or (_pmi_peso < 0 and acao == "venda"):
        score = min(7, score + abs(_pmi_peso))
    elif (_pmi_peso > 0 and acao == "venda") or (_pmi_peso < 0 and acao == "compra"):
        score = max(0, score - 1)

    if padrao_confirma:  score = min(7, score + 1)
    if inverteu_por_candle:    score = min(7, score + 1)   # candle forte de reversão
    if reversao_por_exaustao:  score = min(7, score + 1)   # reversão em extremo do dia
    if padrao_contradiz: score = max(0, score - 2)
    if volume_forte:     score = min(7, score + 1)
    if not volume_ok:    score = max(0, score - 1)

    # Continuação clara contra a direção pretendida
    if acao == "venda" and persistencia_alta:
        score = max(0, score - 3)
    if acao == "compra" and persistencia_baixa:
        score = max(0, score - 3)

    # ---- REVERSÃO NO EXTREMO: o setup mais lucrativo medido ----
    # Vender acima de 60% do range e comprar abaixo de 40% concentrou 14 acertos
    # e nenhum erro. Ganha peso alto; a direção a favor do extremo é penalizada.
    # ---- ABSORÇÃO: indicador de maior acerto medido (77,8%) ----
    _absorcao_now = str(fluxo_info.get("absorcao", "") or "")
    absorcao_favoravel = (
        (_absorcao_now == "compra_absorvendo_venda" and acao == "compra")
        or (_absorcao_now == "venda_absorvendo_compra" and acao == "venda")
    )
    # Nao diferencia mais por direcao: exigir alinhamento derrubou o acerto de
    # 74% para 50%. A absorcao pesa igual nos dois sentidos.
    if _absorcao_now:
        score = min(7, score + 3)

    # ---- PULLBACK: 9 acertos e nenhum erro na amostragem ----
    pullback_favoravel = (
        (regime == "pullback_up" and acao == "compra")
        or (regime == "pullback_down" and acao == "venda")
    )
    if pullback_favoravel:
        score = min(7, score + 3)

    reversao_extremo = False
    zona_morta = False
    if _pr_range >= 0:
        if acao == "venda" and _pr_range >= 62:
            score = min(7, score + 3); reversao_extremo = True
        elif acao == "compra" and _pr_range <= 38:
            score = min(7, score + 3); reversao_extremo = True
        elif acao == "compra" and _pr_range >= PONTA_RANGE_COMPRA:
            score = max(0, score - 4)
        elif acao == "venda" and _pr_range <= PONTA_RANGE_VENDA:
            score = max(0, score - 4)
        else:
            # Faixa 38-62%: 3 acertos contra 8 erros. Sem borda, sem trade.
            zona_morta = True
            score = max(0, score - 2)

    # Confluência explícita de zonas/pontos fortes
    if dist_zona <= 1.5 and forca_zona >= 35:
        if (acao == "compra" and lado_zona in ("suporte", "neutra")) or (acao == "venda" and lado_zona in ("resistencia", "neutra")):
            score = min(7, score + 2)
        else:
            score = max(0, score - 2)
    elif dist_zona <= 3.0 and forca_zona >= 24:
        if (acao == "compra" and lado_zona in ("suporte", "neutra")) or (acao == "venda" and lado_zona in ("resistencia", "neutra")):
            score = min(7, score + 1)
        else:
            score = max(0, score - 1)

    # Fluxo incompleto reduz confiança
    if not zonas_pf.get("tem_agentes_identificados"):
        score = max(0, score - 1)

    # ---- FAIXAS OPERACIONAIS DO DIA ANTERIOR ----
    # Verde autoriza compra, vermelha autoriza venda, amarela pede espera.
    try:
        _faixas = calcular_faixas_operacionais(fechamento_ant, dados_tela)
    except Exception:
        _faixas = {"valido": False, "faixa_atual": "indefinida", "acao_permitida": "",
                   "verde": (0.0, 0.0), "amarela": (0.0, 0.0), "vermelha": (0.0, 0.0),
                   "resumo": "", "amplitude_ant": 0.0, "distancia_faixa": 0.0}
    _fx_confiavel = str(_faixas.get("fonte_referencia", "")) in (
        "tela_pregao_anterior", "tela_pregao_anterior (memoria)",
        "range_acumulado", "historico", "fechamento", "pregao_anterior_historico")
    if _faixas.get("valido") and _fx_confiavel and acao in ("compra", "venda"):
        _fx_acao = str(_faixas.get("acao_permitida", ""))
        if _fx_acao == acao:
            score = min(7, score + 2)      # entrada na faixa da propria direcao
        elif _faixas.get("faixa_atual") == "amarela":
            score = max(0, score - 1)      # zona de indecisao
        elif _fx_acao and _fx_acao not in (acao, "ambas"):
            score = max(0, score - 2)      # comprando na vermelha ou vendendo na verde

    # ---- BOLLINGER / IFR / SCALP ----
    # Volatilidade e oscilacao entram como CONFIRMACAO do setup de borda, nunca
    # como gatilho isolado: banda e IFR sozinhos geram entrada contra tendencia.
    try:
        _boll = calcular_bollinger(dados_tela)
    except Exception:
        _boll = {"valido": False, "estado": "indefinido", "posicao": -1.0,
                 "estreita": False, "toque_superior": False, "toque_inferior": False,
                 "superior": 0.0, "inferior": 0.0, "central": 0.0, "largura_pct": 0.0}
    try:
        _ifr = calcular_ifr(dados_tela)
    except Exception:
        _ifr = {"valido": False, "ifr": 50.0, "estado": "indefinido", "divergencia": ""}
    try:
        _scalp = avaliar_setup_scalp(dados_tela, volume_atual=volume_atual)
    except Exception:
        _scalp = {"vwap_primeiro": False, "ajuste_primeiro": False,
                  "direcao_scalp": "", "volume_perfil": "indefinido",
                  "volume_relativo": 0.0, "motivo": "", "vwap_dist": 0.0,
                  "ajuste_dist": 0.0}

    _boll_confirma = False
    _boll_contradiz = False
    if _boll.get("valido") and acao in ("compra", "venda"):
        # Toque na banda inferior favorece COMPRA; na superior, VENDA. Vale mais
        # em banda estreita (consolidacao), que e o cenario descrito para o WDO.
        if acao == "compra" and _boll.get("toque_inferior"):
            _boll_confirma = True
        elif acao == "venda" and _boll.get("toque_superior"):
            _boll_confirma = True
        elif acao == "compra" and _boll.get("toque_superior"):
            _boll_contradiz = True
        elif acao == "venda" and _boll.get("toque_inferior"):
            _boll_contradiz = True

    _ifr_confirma = False
    _ifr_contradiz = False
    if _ifr.get("valido") and acao in ("compra", "venda"):
        _dv = str(_ifr.get("divergencia", ""))
        if acao == "venda" and (_ifr.get("estado") == "sobrecompra" or _dv == "baixista"):
            _ifr_confirma = True
        elif acao == "compra" and (_ifr.get("estado") == "sobrevenda" or _dv == "altista"):
            _ifr_confirma = True
        elif acao == "compra" and _ifr.get("estado") == "sobrecompra":
            _ifr_contradiz = True
        elif acao == "venda" and _ifr.get("estado") == "sobrevenda":
            _ifr_contradiz = True

    # Scalp de referencia: primeiro toque do dia na VWAP ou no Ajuste.
    # Definido ANTES do score e dos motivos: era usado antes de existir.
    _scalp_ativo = bool(_scalp.get("direcao_scalp"))

    # ---- AJUSTE DE SCORE ----
    # Bollinger + IFR concordando na borda reforca; ambos contra penaliza.
    # Em banda ESTREITA (consolidacao) o toque vale 1 ponto extra: e o cenario
    # de lateralidade descrito para o mini dolar.
    _bonus_estreita = 1 if (_boll.get("valido") and _boll.get("estreita")) else 0
    # Borda de Bollinger com IFR no extremo e o setup de reversao classico:
    # vale 3 pontos, nao 2. Era o que faltava para sair de score 1/3.
    if _boll_confirma and _ifr_confirma:
        score = min(7, score + 3 + _bonus_estreita)
    elif _boll_confirma or _ifr_confirma:
        score = min(7, score + 2 + (_bonus_estreita if _boll_confirma else 0))
    # Volume fraco na borda favorece o repique: e o cenario de scalp.
    if (_boll_confirma or _ifr_confirma) and \
            _scalp.get("volume_perfil") == "fraco_favorece_repique":
        score = min(7, score + 1)
    if _boll_contradiz and _ifr_contradiz:
        score = max(0, score - 2)
    elif _boll_contradiz or _ifr_contradiz:
        score = max(0, score - 1)
    if _scalp_ativo and _scalp.get("direcao_scalp") == acao:
        score = min(7, score + 1)

    # ---- MOTIVOS PARA O PAINEL (depois de todo o ajuste de score) ----
    _motivos_osc = []
    if _boll_confirma:
        _motivos_osc.append(
            f"Bollinger: toque na banda {'inferior' if acao == 'compra' else 'superior'} "
            f"({_boll.get('inferior' if acao == 'compra' else 'superior', 0):.2f})"
            + (" com bandas estreitas" if _boll.get("estreita") else ""))
    if _ifr_confirma:
        _dvt = str(_ifr.get("divergencia", ""))
        _motivos_osc.append(
            f"IFR {_ifr.get('ifr', 0):.0f}"
            + (f" com divergência {_dvt}" if _dvt else f" em {_ifr.get('estado', '')}"))
    if _boll_contradiz:
        _motivos_osc.append(
            f"Bollinger: preço na banda oposta à {acao} — entrada perseguindo o extremo.")
    if _ifr_contradiz:
        _motivos_osc.append(
            f"IFR {_ifr.get('ifr', 0):.0f} em {_ifr.get('estado', '')} contra a {acao}.")
    if _scalp_ativo:
        _motivos_osc.append(_scalp.get("motivo", ""))
    # Volume de rompimento derruba qualquer operacao CONTRA o movimento.
    if _scalp.get("volume_perfil") == "rompimento" and acao in ("compra", "venda"):
        if (acao == "compra" and _boll.get("toque_superior")) or \
           (acao == "venda" and _boll.get("toque_inferior")):
            score = max(0, score - 1)

    # ---- ENTRADA TARDIA: preço esticado demais da MM9 ----
    # Score alto vinha de tendência já madura. Distância da MM9 mede o atraso.
    _dist_mm9 = abs(preco - mm9) if mm9 > 0 else 0.0
    entrada_tardia = False
    gatekeeper_momentum_contra = False
    gatekeeper_momentum_esticado = False
    _mm9_esticada_veto = False
    # Inicializado sempre: com locals() o valor saia 0 no log em 19 de 35 linhas.
    _amp_veto_ini = num((st.session_state.get("ultimo_range_dia") or {}).get("amplitude", 0))
    _lim_veto_mm9 = limite_veto_mm9(_amp_veto_ini)
    if _dist_mm9 >= LIMITE_DIST_MM9_ENTRADA:
        if (acao == "compra" and preco > mm9) or (acao == "venda" and preco < mm9):
            entrada_tardia = True
            gatekeeper_momentum_esticado = True
            # Penalidade PROPORCIONAL: 1 ponto por faixa de 2 pts acima do limite,
            # limitada a 2. Antes tirava 3 pontos de uma vez e derrubava o setup.
            _excesso = _dist_mm9 - LIMITE_DIST_MM9_ENTRADA
            score = max(0, score - min(2, 1 + int(_excesso // 2.0)))
            # Veto proporcional a amplitude do dia, nao mais fixo em 9 pts.
            _amp_veto = num((st.session_state.get("ultimo_range_dia") or {}).get("amplitude", 0))
            _lim_veto_mm9 = limite_veto_mm9(_amp_veto)
            _mm9_esticada_veto = _dist_mm9 >= _lim_veto_mm9

    # Score mínimo FLEXÍVEL: base da estratégia - 2, ajustado pelo horário, mínimo 1
    _min_h = parse_hm(hora)
    _ajuste = ajuste_score_horario(_min_h)  # negativo = mais permissivo
    # Piso elevado: score 4 nao produziu um unico acerto no historico medido.
    # Piso 5 travou o dia inteiro em "Score abaixo do minimo". Volta a 3 e deixa
    # os filtros de range, exaustao e fluxo fazerem a selecao.
    # Score 4 rendeu 3/1; score 6 rendeu 2/4 e score 7, 0/1. Score alto sinaliza
    # tendencia madura. Mantem o piso baixo e deixa a reversao selecionar.
    # Piso elevado de 3 para 4: exige mais convergencia antes de armar.
    score_min = max(SCORE_MINIMO_ABSOLUTO, p["score_minimo_base"] - 2 + _ajuste)
    # Reversao no extremo com pullback foi o unico conjunto com acerto integral
    # no replay; exigir o mesmo score de uma entrada comum travava o setup bom.
    if reversao_extremo and (pullback_favoravel or _absorcao_now):
        score_min = max(2, score_min - 1)
    score = max(score, 1)

    niveis_prov = calcular_fibonacci(preco, acao if acao in ["compra", "venda"] else "compra", est_auto,
                                     dados_tela=dados_tela,
                                     agentes_info=st.session_state.get("ultimos_agentes", {}),
                                     fechamento_ant=fechamento_ant)
    rr_prov = abs(niveis_prov["alvo"] - preco) / abs(niveis_prov["stop"] - preco) if abs(niveis_prov["stop"] - preco) > 0 else 0
    limiar = calcular_limiar_seguranca(preco, vwap, ajuste, mm9, mm20, mm50, mm200, rr_prov, score, score_min)

    # ---------------- Faltas / Motivos de bloqueio ----------------
    falta = []
    if conflito:
        falta.append(f"CONFLITO: MM9 e MM20 divergem (compra={sinais_compra} vs venda={sinais_venda})")
    if exaustao_topo:
        falta.append(f"Exaustão topo: preço a {dist_max:.1f} pts da máxima {maxima_dia:.2f} — aguardar recuo")
    if exaustao_fundo:
        falta.append(f"Exaustão fundo: preço a {dist_min:.1f} pts da mínima {minima_dia:.2f} — aguardar repique")
    if acao == "venda" and persistencia_alta:
        gatekeeper_momentum_contra = True
        falta.append("Preço segue subindo com momentum de alta — venda bloqueada por continuação.")
    if acao == "compra" and persistencia_baixa:
        gatekeeper_momentum_contra = True
        falta.append("Preço segue caindo com momentum de baixa — compra bloqueada por continuação.")
    if padrao_contradiz:
        falta.append(f"Candle {padrao} contradiz {acao} — aguardar confirmação")
    if not volume_ok:
        falta.append(f"Volume fraco ({volume_atual:.0f}) — aguardar volume >= {VOLUME_MINIMO_OK:.0f}")
    if score < score_min:
        falta.append(f"Score {score} abaixo do mínimo {score_min}")
    if entrada_tardia:
        # Veto so no extremo. Entre o limite e o veto, com setup ancorado, a
        # entrada segue valida e o ajuste fica no score e no tamanho.
        if _mm9_esticada_veto and not (reversao_extremo and pullback_favoravel):
            _lv = locals().get("_lim_veto_mm9", LIMITE_DIST_MM9_VETO)
            falta.append(f"Entrada muito esticada: {_dist_mm9:.1f} pts da MM9 "
                         f"(veto em {_lv:.1f}) — aguardar reaproximação.")
            acao_final = "espera"
        else:
            falta.append(f"Preço a {_dist_mm9:.1f} pts da MM9 — entrada esticada, reduzir tamanho.")

    # Se conflito ou exaustão -> forçar espera (mas mantém acao para o resumo)
    acao_final = "espera" if (conflito or exaustao_topo or exaustao_fundo or gatekeeper_momentum_contra) else acao

    # ---- JANELA DE ABERTURA (09:00–09:45): a pior faixa medida ----
    # 0 acertos em 4 tentativas, saldo de -15,5 pts. Na hora cheia: 0/6 e -32,5.
    _min_hora = parse_hm(hora)
    _na_abertura = _min_hora is not None and (9*60) <= _min_hora < (9*60 + 45)
    if _na_abertura and acao_final in ("compra", "venda"):
        if not (absorcao_favoravel or pullback_favoravel):
            acao_final = "espera"
            falta.append("Janela 09:00–09:45 sem absorção nem pullback — faixa de pior desempenho medido.")

    # ---- MOMENTUM FORTE: assimetrico (medido em 37 operacoes fechadas) ----
    # alta_forte : 41,2% de acerto, -20,7 pts em 20 ops -> trava dura
    # baixa_forte: 66,7% de acerto,  +8,0 pts em 17 ops -> so exige ancora com score fraco
    _mom_ancorado = pullback_favoravel or reversao_extremo or bool(_absorcao_now)
    if acao_final in ("compra", "venda") and _mm == "alta_forte" and not _mom_ancorado and gatekeeper_momentum_contra:
        acao_final = "espera"
        falta.append("Momentum alta_forte contra a direção pretendida e sem pullback, reversão ou absorção.")
    elif (acao_final in ("compra", "venda") and _mm == "baixa_forte"
            and not _mom_ancorado and score < score_min):
        acao_final = "espera"
        falta.append("Momentum baixa_forte sem âncora e score abaixo do mínimo.")

    # ---- FILTRO DE FLUXO: agressão mínima OU viés direcional alinhado ----
    # Fluxo neutro/indefinido deixa de autorizar entrada: o saldo de agressão
    # rodava em 55–60% e ainda assim armava gatilho em ambiente sem dono.
    _fx = fluxo_info if isinstance(fluxo_info, dict) else {}
    _agr_pct = num(_fx.get("agressao_pct", 50.0))
    _vies_fx = str((dados_tela or {}).get("vies_fluxo", "indefinido")).strip().lower()
    _tend_fx = str(_fx.get("tendencia", "neutro"))
    _book_ok_fx = bool(_fx.get("valido", False))

    if acao_final in ("compra", "venda") and EXIGE_FLUXO_DIRECIONAL:
        if acao_final == "compra":
            _agr_ok = _agr_pct >= SALDO_AGRESSAO_MINIMO
            _dir_ok = (_vies_fx == "comprador") or (_tend_fx == "compradora_crescente")
        else:
            _agr_ok = _agr_pct <= (100.0 - SALDO_AGRESSAO_MINIMO)
            _dir_ok = (_vies_fx == "vendedor") or (_tend_fx == "vendedora_crescente")
        # Setup ancorado (reversao no extremo + pullback) tolera fluxo morno:
        # o filtro de 65% barrou 4 sinais que atingiram o alvo no replay de 26/08.
        _ancora_forte = bool(reversao_extremo and (pullback_favoravel or _absorcao_now))
        if _ancora_forte:
            _margem = SALDO_AGRESSAO_MINIMO - TOLERANCIA_FLUXO_ANCORADO
            _agr_ok = _agr_ok or (_agr_pct >= _margem if acao_final == "compra"
                                  else _agr_pct <= (100.0 - _margem))
        # Fluxo MORNO (nem a favor, nem contra) so tira score. Fluxo CONTRA
        # continua vetando: e a diferenca entre "sem dono" e "dono do outro lado".
        _fluxo_contra = False
        if acao_final == "compra":
            _fluxo_contra = (_agr_pct <= (50.0 - MARGEM_FLUXO_CONTRARIO)) or (_vies_fx == "vendedor")
        else:
            _fluxo_contra = (_agr_pct >= (50.0 + MARGEM_FLUXO_CONTRARIO)) or (_vies_fx == "comprador")

        # ---- TENDENCIA ACIMA DO FLUXO ----
        # Em tendencia definida e com a entrada A FAVOR dela, agressao contraria
        # costuma ser o lado ERRADO sendo absorvido — foi o que travou o replay
        # de 27/08: preco subindo, book vendedor, 3 compras vetadas.
        _tend_regime = str(regime or "")
        _tend_alta = _tend_regime in ("trend_up", "pullback_up")
        _tend_baixa = _tend_regime in ("trend_down", "pullback_down")
        _a_favor_tendencia = ((acao_final == "compra" and _tend_alta)
                              or (acao_final == "venda" and _tend_baixa))
        _mom_a_favor = ((acao_final == "compra" and _mm in ("alta", "alta_forte"))
                        or (acao_final == "venda" and _mm in ("baixa", "baixa_forte")))
        _tendencia_manda = bool(_a_favor_tendencia and (_mom_a_favor or _pr_range < 0
                                                        or 20 <= _pr_range <= 80))

        if _book_ok_fx and not (_agr_ok or _dir_ok):
            if _fluxo_contra and not _ancora_forte and not _tendencia_manda:
                acao_final = "espera"
                falta.append(
                    f"Fluxo CONTRA a direção — agressão {_agr_pct:.0f}% e viés '{_vies_fx}'.")
            elif _tendencia_manda and _fluxo_contra:
                score = max(0, score - PENALIDADE_FLUXO_MORNO)
                falta.append(
                    f"Fluxo agressor contrário ({_agr_pct:.0f}%) mas entrada a favor da "
                    f"tendência ({_tend_regime}) — score reduzido, direção mantida.")
            else:
                score = max(0, score - PENALIDADE_FLUXO_MORNO)
                falta.append(
                    f"Fluxo morno — agressão {_agr_pct:.0f}% (ideal ≥ {SALDO_AGRESSAO_MINIMO:.0f}%): "
                    f"score reduzido, entrada mantida.")
    contexto_saida_fluxo = {"agressao_pct": _agr_pct, "vies_fluxo_lido": _vies_fx,
                            "tendencia_fluxo": _tend_fx, "fluxo_direcional": bool(_book_ok_fx)}

    # ---- FILTRO DE PERSEGUIÇÃO: não entrar na ponta do movimento ----
    # Entrar comprado no topo do range ou vendido no fundo é perseguir o preço.
    # Só passa quando há rompimento confirmado do candle anterior com volume.
    _rompeu_confirmado = bool(rompimento.get("dispara")) and rompimento.get("direcao") == acao_final
    _pr_valido = _pr_range >= 0
    # Amplitude confiavel: sem ela a posicao no range nao autoriza descartar lado.
    _rg_amplitude_ok = bool((st.session_state.get("ultimo_range_dia") or {}).get("valido"))
    # Em dia de tendencia ampla o preco vive na ponta do range: o teto sobe de
    # 60 para 78 quando a amplitude e grande E a velocidade confirma a direcao.
    # Teto RIGIDO: comprar em cima nunca funcionou, nem em dia de tendencia.
    _teto_compra, _piso_venda = PONTA_RANGE_COMPRA, PONTA_RANGE_VENDA
    if acao_final in ("compra", "venda") and not _rompeu_confirmado and _pr_valido:
        if acao_final == "compra" and _pr_range >= _teto_compra:
            acao_final = "espera"
            falta.append(f"Compra a {_pr_range:.0f}% do range (teto {_teto_compra:.0f}%) — esperar recuo.")
        elif acao_final == "venda" and _pr_range <= _piso_venda:
            acao_final = "espera"
            falta.append(f"Venda a {_pr_range:.0f}% do range — esperar repique.")

    # ---- DIRECAO INCOERENTE COM A POSICAO NO RANGE ----
    # Venda no fundo do dia com momentum de ALTA (e compra no topo com momentum
    # de baixa) foi o unico gatilho de 02/09 e terminou em stop. Nesse caso o
    # erro nao e de timing, e de LADO: derruba a direcao pretendida.
    if _pr_valido and _rg_amplitude_ok:
        _incoerente = ((acao in ("venda",) and _pr_range <= 10 and _mm in ("alta", "alta_forte"))
                       or (acao in ("compra",) and _pr_range >= 90 and _mm in ("baixa", "baixa_forte")))
        if _incoerente:
            acao = "espera"
            acao_final = "espera"
            vies = (f"direção descartada: {_pr_range:.0f}% do range com momentum "
                    f"de {_mm} no sentido oposto")
            falta.insert(0, f"Direção incoerente — {_pr_range:.0f}% do range e momentum de {_mm}.")

    # Teto absoluto: nem rompimento confirmado autoriza entrar na ponta extrema.
    if _pr_valido and acao_final == "compra" and _pr_range >= 88:
        acao_final = "espera"
        falta.append(f"Compra a {_pr_range:.0f}% do range — extremo do dia, entrada vetada.")
    elif _pr_valido and acao_final == "venda" and 0 < _pr_range <= 12:
        acao_final = "espera"
        falta.append(f"Venda a {_pr_range:.0f}% do range — extremo do dia, entrada vetada.")

    # Bloqueio extra quando a zona forte mais próxima é contrária à direção
    _tol_zona = round(1.5 * FATOR_TOLERANCIA_BOOK, 2)  # 1,5 -> 1,73 pts
    if acao_final in ("compra", "venda") and dist_zona <= (3.0 - _tol_zona) and forca_zona >= 35:
        if (acao_final == "compra" and lado_zona == "resistencia") or (acao_final == "venda" and lado_zona == "suporte"):
            acao_final = "espera"

    # ---- JANELA DE EVENTO MACRO ----
    # Antes do indicador o book esvazia e o stop vira loteria; nos primeiros
    # minutos depois ele distorce. A direcao boa aparece com o mercado acomodado.
    # Os valores ficam em variaveis locais e entram no dicionario de retorno no
    # final da funcao — aqui o contexto ainda nao foi montado.
    try:
        _janela_macro = janela_evento_macro()
    except Exception:
        _janela_macro = {"fase": "fora", "evento": "", "peso": 0,
                         "minutos": None, "bloqueia": False, "acelera": False, "resumo": ""}
    _evento_macro_nome = str(_janela_macro.get("evento", "") or "")
    _evento_macro_fase = str(_janela_macro.get("fase", "fora") or "fora")
    _evento_macro_min = _janela_macro.get("minutos")
    if _janela_macro.get("bloqueia") and acao_final in ("compra", "venda"):
        acao_final = "espera"
        falta.insert(0, _janela_macro.get("resumo", "Janela de indicador macro."))

    # ---- VIES MACRO: PMI, DXY, EWZ e VIX empurram a direcao do dolar ----
    try:
        _macro_vies = vies_macro_consolidado(_macro_pmi if not ignorar_macro else {})
    except Exception:
        _macro_vies = {"vies": "neutro", "forca": "neutro", "pontos": 0,
                       "fatores": [], "resumo": ""}
    _macro_vies_lado = str(_macro_vies.get("vies", "neutro") or "neutro")
    _macro_vies_forca = str(_macro_vies.get("forca", "neutro") or "neutro")
    _macro_vies_resumo = str(_macro_vies.get("resumo", "") or "")
    _macro_indisponivel = bool(_macro_vies.get("indisponivel"))
    _macro_parcial = bool(_macro_vies.get("parcial"))
    try:
        _macro_fontes = (_macro_pmi or {}).get("macro_fontes", {}) if not ignorar_macro else {}
    except Exception:
        _macro_fontes = {}
    if _macro_vies_forca == "forte" and acao_final in ("compra", "venda"):
        if _macro_vies_lado != acao_final:
            score = max(0, score - 1)
            falta.append(f"{_macro_vies_resumo} — contra a direcao pretendida.")
        else:
            score = min(7, score + 1)

    # ---- JANELA DE ABERTURA: observar os primeiros minutos, nao operar ----
    # A analise do dia anterior serve de contexto, nunca de gatilho: o robo espera
    # o preco abrir, ve onde abriu e so age quando a tendencia se desenha.
    if abertura_info.get("em_observacao"):
        acao_final = "espera"
        falta.append(abertura_info.get("resumo", "Aguardando os primeiros minutos da abertura."))

    # Logo apos os 5 min, a ancora do dia anterior + tendencia formada ja dao a direcao.
    _tend_ini = abertura_info.get("tendencia_formando", "indefinida")
    _min_pos = int(abertura_info.get("minutos_desde_abertura", 999) or 999)
    if (not abertura_info.get("em_observacao") and 0 <= _min_pos <= 20
            and _tend_ini in ("compra", "venda") and abertura_info.get("referencias")):
        _ref0 = abertura_info["referencias"][0]
        if int(_ref0.get("peso", 0)) >= 3 and acao_final == "espera" and score >= score_min - 1:
            _coerente = ((_tend_ini == "compra" and _ref0.get("lado") == "acima")
                         or (_tend_ini == "venda" and _ref0.get("lado") == "abaixo"))
            if _coerente and lotes_info.get("vies") in (_tend_ini, "neutro"):
                acao = _tend_ini
                acao_final = _tend_ini
                vies = f"abertura ancorada em {_ref0['nivel']} com tendência de {_tend_ini}"
                falta = [f for f in falta if "Score" not in f]

    # ---- PREVISAO FORTE CONTRA A DIRECAO: nao insistir contra o mercado ----
    _pv_dir = previsao.get("direcao_prevista", "indefinido")
    _pv_conf = int(previsao.get("confianca", 0) or 0)
    prox_extra_exaustao = False
    # Medido: previsao com confianca 60+ acertou 39% e a faixa 40-60 acertou 54%.
    # Confianca alta vem de muitos fatores de PRECO empilhados, ou seja, tendencia
    # madura. Ela nao autoriza mais inverter a direcao — apenas suspende a entrada.
    # Confianca 70+ acertou apenas 26%: sinal de tendencia esticada, nao de forca.
    # Ela deixa de vetar a operacao contraria e passa a REFORCAR a reversao.
    if _pv_dir in ("compra", "venda"):
        _contra = "venda" if _pv_dir == "compra" else "compra"
        if _pv_conf >= 70 and acao == _contra and reversao_extremo:
            score = min(7, score + 1)
            prox_extra_exaustao = True
        elif 35 <= _pv_conf < 70 and acao != _pv_dir and acao in ("compra", "venda"):
            acao_final = "espera"
            falta.append(f"Previsão aponta {_pv_dir} ({_pv_conf}%) — aguardar alinhamento.")

    # Nos 30 min seguintes a abertura, so opera a favor da tendencia formada.
    _tend_ab = abertura_info.get("tendencia_formando", "indefinida")
    _min_ab = int(abertura_info.get("minutos_desde_abertura", 999) or 999)
    if (not abertura_info.get("em_observacao") and 0 <= _min_ab <= 30
            and _tend_ab in ("compra", "venda") and acao_final in ("compra", "venda")
            and acao_final != _tend_ab):
        acao_final = "espera"
        falta.append(f"Tendência da abertura é de {_tend_ab} — não operar contra nos primeiros 30 min.")

    # ---- ROMPIMENTO DESACOMPANHADO: 21,7% de acerto, veta a entrada ----
    if (acao_final in ("compra", "venda") and rompimento.get("dispara")
            and not pullback_favoravel and not reversao_extremo):
        acao_final = "espera"
        falta.append("Rompimento sem pullback nem reversão no extremo — 39% de acerto e saldo negativo.")

    # ---- FILTRO MESTRE: só reversão no extremo ----
    # Único setup com expectativa positiva medida (22 acertos / 0 erros).
    # Passe livre pela trava de reversao: pullback (100%) e absorcao (74%).
    # Passe livre ampliado: alem de pullback e absorcao, agora tambem passa a
    # entrada com SCORE FOLGADO a favor da tendencia e a entrada na faixa verde.
    # Antes o filtro exigia reversao no extremo em TODA entrada: em 03/09, 11
    # leituras com score suficiente nao armaram uma unica vez.
    _score_folgado = num(score) >= (num(score_min) + 1)
    _tend_ok = ((acao_final == "compra" and regime in ("trend_up", "pullback_up"))
                or (acao_final == "venda" and regime in ("trend_down", "pullback_down")))
    _faixa_ok = str(_faixas.get("acao_permitida", "")) in (acao_final, "ambas")
    # Coerencia de range: comprar na metade de baixo, vender na metade de cima.
    _coerente_range = (_pr_range < 0
                       or (acao_final == "compra" and _pr_range <= 60)
                       or (acao_final == "venda" and _pr_range >= 40))
    _score_no_minimo = num(score) >= num(score_min)
    _passe_livre = (pullback_favoravel or bool(_absorcao_now)
                    or (_score_folgado and _tend_ok)
                    or (_faixa_ok and _score_folgado)
                    or (_score_no_minimo and _coerente_range and _tend_ok))
    if acao_final in ("compra", "venda") and _pr_range >= 0 and not reversao_extremo and not _passe_livre:
        acao_final = "espera"
        if zona_morta:
            falta.append(f"Preço a {_pr_range:.0f}% do range — zona intermediária sem borda definida.")
        else:
            falta.append(f"{acao} a {_pr_range:.0f}% do range sem reversão, pullback "
                         f"ou score folgado ({int(num(score))}/{int(num(score_min))}).")

    # ---- GRANDES LOTES CONTRA A DIREÇÃO ----
    if acao_final in ("compra", "venda") and lotes_info.get("forca", 0) >= 30:
        if lotes_info.get("vies") and lotes_info["vies"] != acao_final:
            if not rompimento.get("dispara"):
                acao_final = "espera"
                falta.append(f"{lotes_info.get('resumo', 'Grandes lotes')} — contra a direção pretendida.")

    # ---- ROMPIMENTO DE CANDLE: dispara sem esperar o fechamento do candle ----
    # Rompimento so reforca quando esta ALINHADO a reversao no extremo.
    # Sozinho, ele levava a perseguir o movimento (2 acertos em 10 disparos).
    if (rompimento.get("dispara") and rompimento.get("direcao") in ("compra", "venda")
            and rompimento.get("direcao") == acao and reversao_extremo and _absorcao_now):
        acao_final = rompimento["direcao"]
        vies = f"rompimento confirmando reversão em {num(rompimento.get('nivel', 0)):.2f}"
        score = min(7, score + 1)

    # ---------------- ESTRATÉGIA ESPECIAL: Liquidez + Rejeição / Armadilha ----------------
    # Avalia rompimento falso e teste em zona forte com rejeição.
    # Se detectar setup válido, sobrescreve a ação (mesmo que exaustão/conflito tivessem forçado espera).
    _ctx_temp = {"vies_anterior": vies_ant}
    estrategia_especial = avaliar_estrategia_liquidez_e_rejeicao(dados_tela, _ctx_temp, fechamento_ant)
    if estrategia_especial["tipo"] in ["compra", "venda"]:
        acao_final = estrategia_especial["tipo"]
        acao = estrategia_especial["tipo"]  # atualiza para o resumo
        # Estratégia especial vale por cima da exaustão/conflito
        falta = [f for f in falta if not any(k in f for k in ["Exaustão", "CONFLITO", "contradiz"])]
        # Bônus de score por confluência especial detectada
        score = min(7, score + 2)

    if gatekeeper_momentum_esticado and acao_final in ("compra", "venda") and not gatekeeper_momentum_contra:
        acao_final = "espera"
        falta.insert(0, "Entrada a favor, mas esticada da MM9 — aguardar pullback.")

    prox = []
    if corrigido_por_momentum:
        prox.append(f"🔄 Direcao corrigida pelo momentum → {acao}")
    if rompimento.get("dispara"):
        prox.append(f"⚡ {rompimento.get('motivo', '')}")
    elif rompimento.get("direcao") in ("venda_pendente", "compra_pendente"):
        prox.append(f"🎯 {rompimento.get('motivo', '')}")
    if falha_recuperacao_ajuste:
        prox.append(f"📉 Falha de recuperação do ajuste ({rejeicao_ajuste_pts:+.1f} pts)")
    if not integridade_book.get("valido", True):
        prox.append(f"⚠️ {integridade_book.get('motivo', '')}")
    if _absorcao_now:
        prox.append(f"🧲 Absorção detectada — indicador de maior acerto medido (78%)")
    if _mm in ("alta_forte", "baixa_forte"):
        prox.append(f"⚠️ Momentum {_mm} — movimento esticado, 42% de acerto histórico")
    if score >= 7:
        prox.append("🔒 Score 7 (saturado) — confluência máxima indica movimento maduro, entrada vetada")
    if _na_abertura:
        prox.append("🕘 Janela 09:00–09:45 — faixa de pior desempenho, exige absorção ou pullback")
    if pullback_favoravel:
        prox.append(f"📐 Pullback a favor da tendência ({regime}) — 100% de acerto na amostragem")
    if reversao_extremo:
        prox.append(f"↩️ Reversão no extremo: {acao} a {_pr_range:.0f}% do range — setup de alto acerto")
    if zona_morta:
        prox.append(f"⬜ Zona intermediária ({_pr_range:.0f}% do range) — sem borda para operar")
    if prox_extra_exaustao:
        prox.append(f"🔚 Previsão de {_pv_dir} em {_pv_conf}% indica tendência esticada — reforça a reversão")
    if lotes_info.get("resumo"):
        prox.append(f"🏦 {lotes_info['resumo']} → viés {lotes_info.get('vies','neutro')}")
    if abertura_info.get("leitura_antecipada"):
        prox.append(f"🎬 Abertura: {abertura_info['leitura_antecipada']}")
    if fluxo_info.get("absorcao"):
        prox.append(f"🧲 Absorção detectada: {fluxo_info['absorcao'].replace('_', ' ')}")
    if fluxo_info.get("exaustao_fluxo"):
        prox.append(f"🪫 {fluxo_info['exaustao_fluxo'].replace('_', ' ')}")
    if fluxo_info.get("tendencia") not in ("", "neutro"):
        prox.append(f"🌊 Fluxo: {fluxo_info['tendencia'].replace('_', ' ')} ({fluxo_info.get('delta_agressao', 0):+.0f} p.p.)")
    if previsao.get("direcao_prevista") != "indefinido":
        prox.append(f"🤖 Previsão 10 min: {previsao['direcao_prevista']} ({previsao.get('confianca', 0)}% confiança)")
    if zona_mais_proxima:
        prox.append(f"📍 Zona forte {lado_zona} a {dist_zona:.1f} pts | força {forca_zona} | {' + ' .join(rotulos_zona[:3])}")
    if acao == "venda" and persistencia_alta:
        prox.append("⛔ Venda bloqueada: o preço continua subindo com momentum confirmado")
    if acao == "compra" and persistencia_baixa:
        prox.append("⛔ Compra bloqueada: o preço continua caindo com momentum confirmado")
    if _mm in ("alta_forte","baixa_forte"):
        prox.append(f"⚡ Momentum {_mm} ({mom.get('delta_3',0):+.1f} pts em 3 leituras)")
    if pmi_info.get("peso", 0) != 0:
        prox.append(f"🇺🇸 {pmi_info.get('descricao','')}")
    if inverteu_por_candle:
        prox.append(f"🔄 Direção invertida: candle {padrao} sinaliza {acao}")
    if reversao_por_exaustao:
        prox.append(f"🔄 Reversão em extremo do dia → {acao}")
    if estrategia_especial["tipo"] in ["compra", "venda"]:
        prox.append(f"⭐ {estrategia_especial['estrategia']}")
    if padrao_confirma:
        prox.append(f"✓ Candle {padrao} confirma {acao}")
    if volume_forte:
        prox.append(f"✓ Volume forte ({volume_atual})")
    if score >= score_min and not falta:
        prox.append(f"✓ Todos os critérios atendidos — pronto para armar")

    if estrategia_especial["tipo"] in ["compra", "venda"]:
        motivo = estrategia_especial["descricao"]
    else:
        motivo = falta[0] if falta else f"Setup {acao} confluente (score {score}/{score_min})"
    resumo = f"Regime: {regime} | Hora: {hora or 'N/A'} | Estrategia: {est_auto} | Score: {score}/{score_min} | Limiar: {limiar}%"

    return {
        "evento_macro": _evento_macro_nome,
        "fase_macro": _evento_macro_fase,
        "minutos_macro": _evento_macro_min,
        "macro_vies": _macro_vies_lado,
        "macro_forca": _macro_vies_forca,
        "macro_resumo": _macro_vies_resumo,
        "macro_indisponivel": _macro_indisponivel,
        "macro_parcial": _macro_parcial,
        "bollinger_superior": _boll.get("superior", 0.0),
        "bollinger_central": _boll.get("central", 0.0),
        "bollinger_inferior": _boll.get("inferior", 0.0),
        "bollinger_estado": _boll.get("estado", "indefinido"),
        "bollinger_posicao": _boll.get("posicao", -1.0),
        "bollinger_estreita": bool(_boll.get("estreita")),
        "bollinger_largura_pct": _boll.get("largura_pct", 0.0),
        "ifr": _ifr.get("ifr", 50.0),
        "ifr_estado": _ifr.get("estado", "indefinido"),
        "ifr_divergencia": _ifr.get("divergencia", ""),
        "scalp_direcao": _scalp.get("direcao_scalp", ""),
        "scalp_motivo": _scalp.get("motivo", ""),
        "scalp_vwap_primeiro": bool(_scalp.get("vwap_primeiro")),
        "scalp_vwap_dist": _scalp.get("vwap_dist", 0.0),
        "scalp_ajuste_primeiro": bool(_scalp.get("ajuste_primeiro")),
        "scalp_ajuste_dist": _scalp.get("ajuste_dist", 0.0),
        "volume_relativo": _scalp.get("volume_relativo", 0.0),
        "volume_perfil": _scalp.get("volume_perfil", "indefinido"),
        "osciladores_motivos": _motivos_osc,
        "range_dia_maxima": (st.session_state.get("ultimo_range_dia") or {}).get("maxima", 0.0),
        "range_dia_minima": (st.session_state.get("ultimo_range_dia") or {}).get("minima", 0.0),
        "range_dia_amplitude": (st.session_state.get("ultimo_range_dia") or {}).get("amplitude", 0.0),
        "range_dia_valido": bool((st.session_state.get("ultimo_range_dia") or {}).get("valido")),
        "ajuste_origem": _ajuste_origem,
        "faixa_atual": _faixas.get("faixa_atual", "indefinida"),
        "faixa_acao": _faixas.get("acao_permitida", ""),
        "faixa_verde": _faixas.get("verde", (0.0, 0.0)),
        "faixa_amarela": _faixas.get("amarela", (0.0, 0.0)),
        "faixa_vermelha": _faixas.get("vermelha", (0.0, 0.0)),
        "faixa_resumo": _faixas.get("resumo", ""),
        "faixas_validas": bool(_faixas.get("valido")),
        "faixa_data_ref": _faixas.get("data_referencia", ""),
        "faixa_fonte_ref": _faixas.get("fonte_referencia", ""),
        "faixa_maxima_ant": _faixas.get("maxima_ant", 0.0),
        "faixa_minima_ant": _faixas.get("minima_ant", 0.0),
        "faixa_ajuste_ant": _faixas.get("ajuste_ant", 0.0),
        "faixa_ordenada": bool(_faixas.get("ordenadas")),
        "limite_veto_mm9": _lim_veto_mm9,
        "ifr_motivo": _ifr.get("motivo", ""),
        "tendencia_sobrepoe_fluxo": bool(locals().get("_tendencia_manda", False)),
        "macro_fontes": _macro_fontes,
        "estrategia": est_auto, "regime": regime, "acao_objetiva": acao_final,
        "acao_pretendida": acao, "vies": vies, "conflito": conflito,
        "momentum": _mm, "delta_preco": mom.get("delta_preco",0), "delta_3": mom.get("delta_3",0),
        "persistencia_alta": persistencia_alta, "persistencia_baixa": persistencia_baixa,
        "inclinacao_mm9": mom.get("inclinacao_mm9",0), "inclinacao_mm20": mom.get("inclinacao_mm20",0),
        "pos_range": _pr_range, "corrigido_por_momentum": corrigido_por_momentum,
        "pmi_valor": pmi_info.get("pmi"), "pmi_vies": pmi_info.get("vies","neutro"),
        "pmi_peso": pmi_info.get("peso",0), "pmi_descricao": pmi_info.get("descricao",""),
        "padrao_candle": padrao, "padrao_confirma": padrao_confirma, "padrao_contradiz": padrao_contradiz,
        "inverteu_por_candle": inverteu_por_candle, "reversao_por_exaustao": reversao_por_exaustao,
        "volume_atual": volume_atual, "volume_ok": volume_ok, "volume_forte": volume_forte,
        "exaustao_topo": exaustao_topo, "exaustao_fundo": exaustao_fundo,
        "dist_max_dia": round(dist_max,2) if dist_max<999 else 0,
        "dist_min_dia": round(dist_min,2) if dist_min<999 else 0,
        "motivo_objetivo": motivo, "resumo_objetivo": resumo, "score": score,
        "score_minimo_usado": score_min, "vies_anterior": vies_ant, "validacao": val, "limiar": limiar,
        "agressao_pct_leitura": contexto_saida_fluxo.get("agressao_pct", 50.0),
        "vies_fluxo_lido": contexto_saida_fluxo.get("vies_fluxo_lido", "indefinido"),
        "tendencia_fluxo": contexto_saida_fluxo.get("tendencia_fluxo", "neutro"),
        "falta_para_gatilho": falta,
        "condicao_mais_proxima": prox,
        "dist_vwap": round(preco - vwap, 2) if vwap > 0 else 0,
        "dist_ajuste": round(preco - ajuste, 2) if ajuste > 0 else 0,
        "dist_mm9": round(preco - mm9, 2) if mm9 > 0 else 0,
        "dist_mm20": round(preco - mm20, 2) if mm20 > 0 else 0,
        "dist_mm50": round(preco - mm50, 2) if mm50 > 0 else 0,
        "dist_mm200": round(preco - mm200, 2) if mm200 > 0 else 0,
        "previsao": previsao,
        "previsao_direcao": previsao.get("direcao_prevista", "indefinido"),
        "previsao_prob_alta_5": previsao.get("prob_alta_5", 50),
        "previsao_prob_alta_10": previsao.get("prob_alta_10", 50),
        "previsao_projecao_5": previsao.get("projecao_5", 0),
        "previsao_projecao_10": previsao.get("projecao_10", 0),
        "previsao_confianca": previsao.get("confianca", 0),
        "previsao_velocidade": previsao.get("velocidade_pts_min", 0),
        "rompimento_candle": rompimento,
        "rompimento_dispara": bool(rompimento.get("dispara")),
        "rompimento_direcao": rompimento.get("direcao", "espera"),
        "rompimento_nivel": rompimento.get("nivel", 0),
        "rompimento_stop_venda": rompimento.get("nivel_stop_venda", 0),
        "rompimento_stop_compra": rompimento.get("nivel_stop_compra", 0),
        "volume_projetado": rompimento.get("volume_projetado", 0),
        "lotes_institucionais": lotes_info,
        "lotes_vies": lotes_info.get("vies", ""),
        "lotes_forca": lotes_info.get("forca", 0),
        "lotes_defesa": lotes_info.get("defesa", 0),
        "lotes_teto": lotes_info.get("teto", 0),
        "abertura_ancora": abertura_info.get("ancora", ""),
        "abertura_leitura": abertura_info.get("leitura_antecipada", ""),
        "abertura_info": abertura_info,
        "abertura_em_observacao": abertura_info.get("em_observacao", False),
        "abertura_resumo": abertura_info.get("resumo", ""),
        "abertura_gap_pts": abertura_info.get("gap_pts", 0),
        "abertura_tipo": abertura_info.get("tipo_abertura", ""),
        "abertura_tendencia": abertura_info.get("tendencia_formando", ""),
        "regime_falado": regime_em_palavras(regime),
        "fluxo_pressao": fluxo_info,
        "fluxo_tendencia": fluxo_info.get("tendencia", ""),
        "fluxo_absorcao": fluxo_info.get("absorcao", ""),
        "fluxo_exaustao": fluxo_info.get("exaustao_fluxo", ""),
        "fluxo_desequilibrio": fluxo_info.get("desequilibrio", 0),
        "fluxo_delta_agressao": fluxo_info.get("delta_agressao", 0),
        "fluxo_valido": fluxo_info.get("valido", False),
        "na_janela_abertura": _na_abertura,
        "momentum_forte_penalizado": _mm in ("alta_forte", "baixa_forte"),
        "absorcao_favoravel": absorcao_favoravel,
        "pullback_favoravel": pullback_favoravel,
        "reversao_extremo": reversao_extremo,
        "zona_morta": zona_morta,
        "entrada_tardia": entrada_tardia,
        "dist_mm9_abs": round(_dist_mm9, 2),
        "falha_recuperacao_ajuste": falha_recuperacao_ajuste,
        "rejeicao_ajuste_pts": rejeicao_ajuste_pts,
        "book_valido": integridade_book.get("valido", True),
        "book_motivo": integridade_book.get("motivo", ""),
        "zonas_pontos_fortes": zonas_pf,
        "zona_mais_proxima_lado": lado_zona,
        "zona_mais_proxima_distancia": round(dist_zona, 2) if dist_zona < 999 else 0,
        "zona_mais_proxima_forca": forca_zona,
        "zona_mais_proxima_rotulos": rotulos_zona,
        "gestao_posicao": niveis_prov.get("gestao", ""),
        "alvo_parcial": niveis_prov.get("alvo_parcial", 0),
        "breakeven_em": niveis_prov.get("breakeven_em", 0),
        "trailing_dist": niveis_prov.get("trailing_dist", 0),
        "amplitude_dia": niveis_prov.get("amplitude_dia", 0),
        "zona_exaustao_pts": round(_zona_ex, 2),
        "teto_range_compra": _teto_compra,
        "piso_range_venda": _piso_venda,
        "alvo_prov": niveis_prov.get("alvo", 0),
        "stop_prov": niveis_prov.get("stop", 0),
        "base_alvo": niveis_prov.get("base_alvo", "fixo"),
        "base_stop": niveis_prov.get("base_stop", "fixo"),
        "dist_alvo": niveis_prov.get("dist_alvo", 0),
        "dist_stop": niveis_prov.get("dist_stop", 0),
        "estrategia_especial_tipo": estrategia_especial.get("tipo", "espera"),
        "estrategia_especial_nome": estrategia_especial.get("estrategia", "Nenhuma"),
        "estrategia_especial_desc": estrategia_especial.get("descricao", ""),
    }

def _coletar_obstaculos(preco, acao, dados_tela, agentes_info, fechamento_ant):
    """Reune todos os niveis tecnicos relevantes A FRENTE do preco, no sentido da operacao.
    Retorna lista de dicts {preco, tipo, peso} ordenada do mais proximo ao mais distante.
    peso: 1=fraco  2=medio  3=forte (parede de liquidez / fibo forte / mm200)."""
    dados_tela = dados_tela or {}
    niveis = []

    def _add(v, tipo, peso):
        v = num(v)
        if v <= 0 or preco <= 0: return
        if acao == "compra" and v > preco + 0.5: niveis.append({"preco": v, "tipo": tipo, "peso": peso})
        elif acao == "venda" and v < preco - 0.5: niveis.append({"preco": v, "tipo": tipo, "peso": peso})

    # --- Medias moveis e referencias da tela ---
    _add(dados_tela.get("mm9"),   "MM9",   1)
    _add(dados_tela.get("mm20"),  "MM20",  2)
    _add(dados_tela.get("mm50"),  "MM50",  2)
    _add(dados_tela.get("mm200"), "MM200", 3)
    _add(dados_tela.get("vwap"),  "VWAP",  3)
    _add(dados_tela.get("ajuste"),"Ajuste",2)
    _add(dados_tela.get("maxima"),"Maxima do dia", 3)
    _add(dados_tela.get("minima"),"Minima do dia", 3)

    # --- Pivos classicos e extremos do dia anterior ---
    _fa = fechamento_ant or {}
    _piv = calcular_pivot_points(
        num(_fa.get("maxima_dia", 0)), num(_fa.get("minima_dia", 0)),
        num(_fa.get("preco", 0)) or num(dados_tela.get("ajuste", 0)),
    )
    _add(_piv.get("pivot"), "Pivô", 3)
    _add(_piv.get("r1"), "R1", 3); _add(_piv.get("s1"), "S1", 3)
    _add(_piv.get("r2"), "R2", 2); _add(_piv.get("s2"), "S2", 2)
    _add(_piv.get("r3"), "R3", 1); _add(_piv.get("s3"), "S3", 1)
    _add(_fa.get("maxima_dia"), "Máxima D-1", 3)
    _add(_fa.get("minima_dia"), "Mínima D-1", 3)
    _add(_fa.get("vwap"), "VWAP D-1", 2)
    _add(_fa.get("preco"), "Fechamento D-1", 2)
    _add(dados_tela.get("abertura"), "Abertura do dia", 2)

    # --- Fibonacci do dia anterior ---
    fib = (fechamento_ant or {}).get("fibonacci_diario", {}) or {}
    _add(fib.get("nivel_236"), "Fibo 23,6%", 1)
    _add(fib.get("nivel_382"), "Fibo 38,2%", 3)
    _add(fib.get("nivel_50"),  "Fibo 50%",   3)
    _add(fib.get("nivel_618"), "Fibo 61,8%", 3)
    _add(fib.get("nivel_786"), "Fibo 78,6%", 1)

    # --- Paredes de liquidez do book (SuperDom / agentes) ---
    ag = agentes_info or {}
    if acao == "compra":
        for o in (ag.get("ofertantes_venda") or [])[:5]:
            _qt = int(o.get("qtde", 0) or 0)
            _add(o.get("preco"), f"Oferta venda {_qt} ({str(o.get('agente','?'))[:14]})", 3 if _qt >= 1000 else 2)
    else:
        for o in (ag.get("ofertantes_compra") or [])[:5]:
            _qt = int(o.get("qtde", 0) or 0)
            _add(o.get("preco"), f"Oferta compra {_qt} ({str(o.get('agente','?'))[:14]})", 3 if _qt >= 1000 else 2)
    _add(ag.get("nivel_liquidez_forte"), "Liquidez forte (fluxo)", 3)

    niveis.sort(key=lambda x: abs(x["preco"] - preco))
    return niveis


def calcular_pivot_points(maxima, minima, fechamento):
    if maxima <= 0 or minima <= 0 or fechamento <= 0:
        return {}
    p = (maxima + minima + fechamento) / 3.0
    r1 = 2 * p - minima
    s1 = 2 * p - maxima
    r2 = p + (maxima - minima)
    s2 = p - (maxima - minima)
    r3 = maxima + 2 * (p - minima)
    s3 = minima - 2 * (maxima - p)
    return {
        "pivot": round(p, 2),
        "r1": round(r1, 2), "r2": round(r2, 2), "r3": round(r3, 2),
        "s1": round(s1, 2), "s2": round(s2, 2), "s3": round(s3, 2),
    }


def consolidar_zonas_pontos_fortes(dados_tela, fechamento_ant=None, agentes_info=None, tolerancia=2.0):
    preco = num(dados_tela.get("preco_atual", 0))
    maxima = num(dados_tela.get("maxima", 0))
    minima = num(dados_tela.get("minima", 0))
    abertura = num(dados_tela.get("abertura", 0))
    vwap = num(dados_tela.get("vwap", 0))
    ajuste = num(dados_tela.get("ajuste", 0))
    mm9 = num(dados_tela.get("mm9", 0))
    mm20 = num(dados_tela.get("mm20", 0))
    mm50 = num(dados_tela.get("mm50", 0))
    mm200 = num(dados_tela.get("mm200", 0))

    fechamento_ref = num((fechamento_ant or {}).get("preco", 0)) or ajuste or preco
    pivot = calcular_pivot_points(maxima, minima, fechamento_ref)
    fib_ant = (fechamento_ant or {}).get("fibonacci_diario", {}) or {}

    refs = []

    def add_ref(preco_ref, nome, categoria, peso):
        p = num(preco_ref)
        if p <= 0:
            return
        refs.append({
            "nome": nome,
            "categoria": categoria,
            "preco": round(p, 2),
            "peso": int(peso),
        })

    add_ref(vwap, "VWAP", "intraday", 3)
    add_ref(ajuste, "Ajuste", "institucional", 3)
    add_ref(abertura, "Abertura", "intraday", 2)
    add_ref(maxima, "Máxima do dia", "extremo", 4)
    add_ref(minima, "Mínima do dia", "extremo", 4)
    add_ref(mm9, "MM9", "media", 1)
    add_ref(mm20, "MM20", "media", 2)
    add_ref(mm50, "MM50", "media", 3)
    add_ref(mm200, "MM200", "media", 4)

    add_ref(pivot.get("pivot"), "Pivot", "pivot", 3)
    add_ref(pivot.get("r1"), "R1", "pivot", 2)
    add_ref(pivot.get("r2"), "R2", "pivot", 2)
    add_ref(pivot.get("r3"), "R3", "pivot", 1)
    add_ref(pivot.get("s1"), "S1", "pivot", 2)
    add_ref(pivot.get("s2"), "S2", "pivot", 2)
    add_ref(pivot.get("s3"), "S3", "pivot", 1)

    add_ref(fib_ant.get("nivel_236"), "Fibo D-1 23,6%", "fibo", 1)
    add_ref(fib_ant.get("nivel_382"), "Fibo D-1 38,2%", "fibo", 2)
    add_ref(fib_ant.get("nivel_50"), "Fibo D-1 50%", "fibo", 2)
    add_ref(fib_ant.get("nivel_618"), "Fibo D-1 61,8%", "fibo", 3)
    add_ref(fib_ant.get("nivel_786"), "Fibo D-1 78,6%", "fibo", 1)

    ag = agentes_info or {}
    for o in (ag.get("ofertantes_compra") or [])[:5]:
        qt = int(o.get("qtde", 0) or 0)
        peso = 4 if qt >= 1500 else (3 if qt >= 1000 else 2)
        add_ref(o.get("preco"), f"Bid {qt} {str(o.get('agente', 'BOOK'))[:12]}", "liquidez_bid", peso)
    for o in (ag.get("ofertantes_venda") or [])[:5]:
        qt = int(o.get("qtde", 0) or 0)
        peso = 4 if qt >= 1500 else (3 if qt >= 1000 else 2)
        add_ref(o.get("preco"), f"Ask {qt} {str(o.get('agente', 'BOOK'))[:12]}", "liquidez_ask", peso)

    refs = sorted(refs, key=lambda x: x["preco"])
    zonas = []
    atual = None

    for ref in refs:
        if atual is None:
            atual = {
                "preco_medio": ref["preco"],
                "min_preco": ref["preco"],
                "max_preco": ref["preco"],
                "peso_total": ref["peso"],
                "referencias": [ref],
            }
            continue
        if abs(ref["preco"] - atual["preco_medio"]) <= tolerancia:
            atual["referencias"].append(ref)
            atual["peso_total"] += ref["peso"]
            atual["min_preco"] = min(atual["min_preco"], ref["preco"])
            atual["max_preco"] = max(atual["max_preco"], ref["preco"])
            atual["preco_medio"] = round(sum(r["preco"] for r in atual["referencias"]) / len(atual["referencias"]), 2)
        else:
            zonas.append(atual)
            atual = {
                "preco_medio": ref["preco"],
                "min_preco": ref["preco"],
                "max_preco": ref["preco"],
                "peso_total": ref["peso"],
                "referencias": [ref],
            }
    if atual:
        zonas.append(atual)

    for z in zonas:
        z["distancia_preco"] = round(abs(preco - z["preco_medio"]), 2) if preco > 0 else 0
        acima = sum(1 for r in z["referencias"] if r["preco"] > preco)
        abaixo = sum(1 for r in z["referencias"] if r["preco"] < preco)
        if acima > abaixo:
            lado = "resistencia"
        elif abaixo > acima:
            lado = "suporte"
        else:
            lado = "neutra"
        z["lado"] = lado
        z["forca"] = min(100, z["peso_total"] * 8 + (len(z["referencias"]) - 1) * 10)
        z["rotulos"] = [r["nome"] for r in z["referencias"]]

    zonas = sorted(zonas, key=lambda z: (-z["forca"], z["distancia_preco"]))
    zonas_suporte = [z for z in zonas if z["lado"] in ("suporte", "neutra")][:5]
    zonas_resistencia = [z for z in zonas if z["lado"] in ("resistencia", "neutra")][:5]

    zona_mais_proxima = None
    if zonas:
        zona_mais_proxima = min(zonas, key=lambda z: z["distancia_preco"])

    return {
        "pivot_points": pivot,
        "referencias": refs,
        "zonas": zonas,
        "zonas_suporte": zonas_suporte,
        "zonas_resistencia": zonas_resistencia,
        "zona_mais_proxima": zona_mais_proxima,
        "tem_agentes_identificados": bool((ag.get("tem_nomes_agentes") is True)),
        "fonte_book": "agentes" if ag.get("tem_nomes_agentes") else "superdom",
        "rotulo_liquidez": "MAIORES AGENTES NA LIQUIDEZ" if ag.get("tem_nomes_agentes") else "MAIORES PAREDES DE LIQUIDEZ DO BOOK",
    }


def calcular_alvo_dinamico(preco, acao, estrategia, dados_tela=None, agentes_info=None, fechamento_ant=None):
    """Define alvo e stop com base no MAPA REAL DO MERCADO em vez de pontos fixos.

    ALVO  = primeiro obstaculo relevante a frente (media, fibo forte ou parede de liquidez),
            recuado 0,5 pt para entrar antes da parede. Respeita piso e teto por estrategia.
    STOP  = ultimo suporte/resistencia ATRAS do preco + folga, limitado pelo stop maximo.
    """
    p = ESTRATEGIAS[estrategia]
    # Sem direcao definida NAO existe geometria. Cair no ramo de compra era o
    # que colocava alvo ACIMA do preco em leitura com vies de venda.
    _acao_norm = str(acao or "").strip().lower()
    if _acao_norm not in ("compra", "venda"):
        return {"alvo": 0.0, "stop": 0.0, "base_alvo": "indefinido",
                "base_stop": "indefinido", "dist_alvo": 0.0, "dist_stop": 0.0,
                "geometria_valida": False}
    acao = _acao_norm

    alvo_fixo = p["amp_fibo"] * 1.61
    stop_fixo = p["stop_pts"]

    # limites de sanidade por estrategia (mini dolar)
    # Limites ADAPTATIVOS: escalam com a amplitude real do dia em vez de fixos.
    # Num dia de 70 pts o alvo maximo de 12 e pequeno demais; num dia de 15 e grande.
    _amp_dia = 0.0
    _mx, _mn = num((dados_tela or {}).get("maxima", 0)), num((dados_tela or {}).get("minima", 0))
    if _mx > _mn > 0:
        _amp_dia = _mx - _mn
    _hc_vol = st.session_state.get("hist_candles", [])
    _amps = [num(c.get("maxima", 0)) - num(c.get("minima", 0))
             for c in _hc_vol[:5] if num(c.get("maxima", 0)) > num(c.get("minima", 0)) > 0]
    _amp_candle = (sum(_amps) / len(_amps)) if _amps else 0.0

    _base_max = 8.0 if estrategia == "Conservador" else (12.0 if estrategia == "Agressividade Média" else 16.0)
    if _amp_dia > 0:
        _fator = max(0.5, min(1.3, _amp_dia / 40.0))
        alvo_max = round(max(4.0, min(_base_max * _fator, 9.0)), 1)
    else:
        alvo_max = min(_base_max, 6.0)
    # Alvo ancorado no que o mercado REALMENTE entrega (media capturada ~2 pts).
    alvo_min = round(max(2.5, min(4.5, _amp_candle * 0.45)), 1) if _amp_candle > 0 else 3.0
    if alvo_min >= alvo_max:
        alvo_min = max(4.0, alvo_max * 0.5)

    if preco <= 0 or acao not in ("compra", "venda"):
        if acao == "venda":
            return {"alvo": preco - alvo_fixo, "stop": preco + stop_fixo,
                    "base_alvo": "fixo", "base_stop": "fixo", "dist_alvo": alvo_fixo, "dist_stop": stop_fixo}
        return {"alvo": preco + alvo_fixo, "stop": preco - stop_fixo,
                "base_alvo": "fixo", "base_stop": "fixo", "dist_alvo": alvo_fixo, "dist_stop": stop_fixo}

    obst = _coletar_obstaculos(preco, acao, dados_tela, agentes_info, fechamento_ant)

    # ---------- ALVO ----------
    base_alvo, dist_alvo = "fixo (sem referencia proxima)", alvo_fixo
    for o in obst:
        d = abs(o["preco"] - preco)
        if d < alvo_min: continue            # perto demais: nao vale o risco
        if o["peso"] < 2: continue           # ignora referencia fraca como alvo
        if d > alvo_max: break               # longe demais: usa teto da estrategia
        dist_alvo = max(alvo_min, d - 0.5)   # entra 0,5 pt antes da parede
        base_alvo = o["tipo"]
        break
    dist_alvo = min(alvo_max, max(alvo_min, dist_alvo))

    # ---------- STOP ----------
    # procura a referencia mais proxima ATRAS do preco (sentido inverso)
    acao_inv = "venda" if acao == "compra" else "compra"
    obst_tras = _coletar_obstaculos(preco, acao_inv, dados_tela, agentes_info, fechamento_ant)
    base_stop, dist_stop = "fixo", stop_fixo
    for o in obst_tras:
        d = abs(o["preco"] - preco)
        if d < 2.0: continue
        if o["peso"] < 2: continue
        if d > stop_fixo + 2.0: break
        dist_stop = d + 1.0                  # 1 pt de folga alem do suporte
        base_stop = o["tipo"]
        break
    # Stop adaptativo: acompanha a amplitude media dos candios recentes.
    _stop_teto = max(stop_fixo + 2.0, _amp_candle * 1.1) if _amp_candle > 0 else stop_fixo + 2.0
    _stop_piso = max(3.0, _amp_candle * 0.45) if _amp_candle > 0 else 3.0
    dist_stop = min(_stop_teto, max(_stop_piso, dist_stop))

    # ---------- Garantia de RR minimo ----------
    # RR minimo real de 1,3: o alvo precisa pagar o risco assumido.
    if dist_alvo / dist_stop < 1.3:
        dist_alvo = min(alvo_max, dist_stop * 1.4)
        base_alvo += " (ajustado por RR)"
    # Se nem assim o RR fecha, encurta o stop em vez de esticar o alvo.
    if dist_alvo / dist_stop < 1.2:
        dist_stop = max(3.5, dist_alvo / 1.3)
        base_stop += " (encurtado por RR)"

    if acao == "compra":
        alvo, stop = preco + dist_alvo, preco - dist_stop
    else:
        alvo, stop = preco - dist_alvo, preco + dist_stop

    # ---------- GESTAO DINAMICA DA POSICAO ----------
    # Medido: alvo medio de 6,5 pts com apenas 1,5 pt realmente capturado.
    # O preco anda a favor e devolve. Parcial + breakeven protegem esse ganho.
    _d_parcial = round(max(1.5, dist_alvo * 0.40), 2)
    _d_be = round(max(1.0, dist_alvo * 0.25), 2)
    _d_trail = round(max(2.5, dist_stop * 0.8), 2)
    if acao == "compra":
        _p_parcial, _p_be = preco + _d_parcial, preco + _d_be
    else:
        _p_parcial, _p_be = preco - _d_parcial, preco - _d_be

    return {"alvo": round(alvo, 2), "stop": round(stop, 2),
            "base_alvo": base_alvo, "base_stop": base_stop,
            "dist_alvo": round(dist_alvo, 2), "dist_stop": round(dist_stop, 2),
            "alvo_parcial": round(_p_parcial, 2), "dist_parcial": _d_parcial,
            "breakeven_em": round(_p_be, 2), "dist_breakeven": _d_be,
            "trailing_dist": _d_trail,
            "amplitude_dia": round(_amp_dia, 1),
            "amplitude_candle": round(_amp_candle, 1),
            "gestao": (f"Parcial em {_p_parcial:.2f} (+{_d_parcial:.1f}) · "
                       f"stop no zero a zero após {_d_be:.1f} pts · "
                       f"trailing de {_d_trail:.1f} pts"),
            "obstaculos": obst[:4]}


def calcular_fibonacci(p1, acao, estrategia, dados_tela=None, agentes_info=None, fechamento_ant=None):
    """Compativel com as chamadas antigas. Quando recebe contexto, usa alvo dinamico."""
    if dados_tela or agentes_info or fechamento_ant:
        return calcular_alvo_dinamico(p1, acao, estrategia, dados_tela, agentes_info, fechamento_ant)
    p = ESTRATEGIAS[estrategia]
    amp, spt = p["amp_fibo"], p["stop_pts"]
    if acao=="compra": return {"alvo": p1+amp*1.61, "stop": p1-spt, "base_alvo":"fixo", "base_stop":"fixo"}
    return {"alvo": p1-amp*1.61, "stop": p1+spt, "base_alvo":"fixo", "base_stop":"fixo"}


def calcular_pct(tipo, entrada, alvo, stop, maxima, minima):
    if entrada<=0 or alvo<=0 or stop<=0:
        return {"PctAcerto":0,"PctPerda":0,"PontosFavoraveis":0,"PontosContra":0,"StatusEstimado":"SEM_DADOS"}
    if tipo=="VENDA":
        pf=max(0,entrada-minima) if minima>0 else 0; pc=max(0,maxima-entrada) if maxima>0 else 0
        pg=max(0.01,entrada-alvo); pp=max(0.01,stop-entrada)
    elif tipo=="COMPRA":
        pf=max(0,maxima-entrada) if maxima>0 else 0; pc=max(0,entrada-minima) if minima>0 else 0
        pg=max(0.01,alvo-entrada); pp=max(0.01,entrada-stop)
    else:
        return {"PctAcerto":0,"PctPerda":0,"PontosFavoraveis":0,"PontosContra":0,"StatusEstimado":"SEM_GATILHO"}
    pa=round(min(999,(pf/pg)*100),2); ppa=round(min(999,(pc/pp)*100),2)
    if pa>=100: st2="ACERTO_ALVO"
    elif ppa>=100: st2="ERRO_STOP"
    elif pa>ppa and pa>0: st2="ACERTO_PARCIAL"
    elif ppa>pa and ppa>0: st2="ERRO_PARCIAL"
    else: st2="NEUTRO"
    return {"PctAcerto":pa,"PctPerda":ppa,"PontosFavoraveis":round(pf,2),"PontosContra":round(pc,2),"StatusEstimado":st2}


def chave_gatilho(r):
    return (str(r.get("DataEvento","")),str(r.get("Estrategia","")),str(r.get("StatusGatilho","")),
            str(r.get("Tipo","")),round(float(r.get("PrecoEntrada",0) or 0),1),round(float(r.get("Alvo",0) or 0),1))


def calcular_direcao_correta(status_est):
    """
    Calcula se o gatilho foi na direção correta independentemente de atingir o alvo.
    sim      = ACERTO_ALVO ou ACERTO_PARCIAL (movimento a favor)
    nao      = ERRO_STOP ou ERRO_PARCIAL (movimento contra)
    pendente = sem dados suficientes
    """
    s = str(status_est or "")
    if s in ["ACERTO_ALVO", "ACERTO_PARCIAL"]: return "sim"
    if s in ["ERRO_STOP", "ERRO_PARCIAL"]:     return "nao"
    return "pendente"


def salvar_historico(registro):
    registro["DirecaoCorreta"] = calcular_direcao_correta(registro.get("StatusEst",""))
    if st.session_state.bloquear_gatilho_repetido:
        nova = chave_gatilho(registro)
        for item in st.session_state.historico_trades:
            if chave_gatilho(item)==nova: return False,"Duplicado."
    st.session_state.historico_trades.append(registro)
    try:
        df = pd.DataFrame(st.session_state.historico_trades)
        if "DataRegistro" in df.columns:
            df["_ord"]=pd.to_datetime(df["DataRegistro"],errors="coerce")
            df=df.sort_values("_ord",ascending=False).drop(columns=["_ord"])
        df.to_csv(HISTORICO_CSV, index=False)
        st.session_state.historico_trades = df.to_dict(orient="records")
        return True,""
    except Exception as e:
        return False,str(e)


# =========================
# ANALISE DE FLUXO — SuperDom + Times & Trades
# =========================
def analisar_agentes_com_ia(img_agentes, img_tt=None, img_tt_oo=None, imgs_extra=None):
    if img_agentes is None and img_tt is None and img_tt_oo is None and not imgs_extra:
        return {
            "agente_agora": {"acao": "sem_dados", "preco_compra": 0.0, "preco_venda": 0.0, "qtde": 0, "obs": "Nenhuma imagem"},
            "agentes_ativos": [], "liquidez_forte": [], "desalavancagem": {"detectada": False, "descricao": ""},
            "resumo_agentes": "Painéis de agentes/T&T nao capturados."
        }

    partes = [{"type":"text","text":"""Analise até 3 imagens do Profit (podem vir 1, 2 ou 3):
- Imagem 1: Book/painel de Agentes (colunas Compra, Venda, Qtd, agente por preço)
- Imagem 2: Times & Trades — aba Negócios (execuções em tempo real com Comprador × Vendedor × Agressor)
- Imagem 3: Times & Trades — aba Ordem Original (ordens agrupadas por corretora ao longo do tempo)

Use TODAS as imagens juntas para cruzar quem oferta liquidez, quem executa agressão e quem repete ordens. Correlacione os agentes que aparecem em várias imagens.

TAREFA PRINCIPAL: Identifique os MAIORES OFERTANTES DE LIQUIDEZ visíveis no book.
Ou seja: quais corretoras/agentes estão com os MAIORES LOTES posicionados para COMPRA (lado do bid) e para VENDA (lado do ask), com seus respectivos preços.

Corretoras comuns no book brasileiro: Agora, XP, BTG, JP Morgan, Itau, Ideal, Mirae, Nova Futura, BGC Liquidez, Necton, Elliot-Warren, Tullett, Santander, Genial, C6, CM Capital, Morgan Stanley, RLP, UBS, Bradesco, Safra, Modal, Terra, Ativa, Genoa.

Responda APENAS em JSON válido, sem markdown, sem comentários. Retorne pelo menos 3 ofertantes em cada lado (compra e venda), ordenados do MAIOR para o menor lote. Se o painel mostrar menos, retorne os que houver.

FORMATO OBRIGATÓRIO — TODOS os campos devem existir na resposta:
{
  "ofertantes_compra": [
    {"agente": "BGC Liquidez", "preco": 5088.00, "qtde": 1500},
    {"agente": "Itau", "preco": 5087.50, "qtde": 850},
    {"agente": "XP", "preco": 5087.00, "qtde": 600}
  ],
  "ofertantes_venda": [
    {"agente": "JP Morgan", "preco": 5100.00, "qtde": 1200},
    {"agente": "BTG", "preco": 5100.50, "qtde": 900},
    {"agente": "Morgan Stanley", "preco": 5101.00, "qtde": 700}
  ],
  "tem_nomes_agentes": true,
  "tipo_painel": "book_agentes ou superdom",
  "saldo_agentes": "comprador",
  "top_compradores": ["BGC Liquidez", "Itau", "XP"],
  "top_vendedores": ["JP Morgan", "BTG", "Morgan Stanley"],
  "liquidez_forte": [
    {"tipo": "compra", "preco": 5088.00, "qtde": 1500, "agente": "BGC Liquidez"},
    {"tipo": "venda", "preco": 5100.00, "qtde": 1200, "agente": "JP Morgan"}
  ],
  "desalavancagem": {"detectada": false, "lado": "", "descricao": ""},
  "agressao_dominante": "vendedor",
  "agressao_compradora_pct": 42,
  "agressao_vendedora_pct": 58,
  "resumo_agentes": "texto curto descrevendo quem domina cada lado"
}

IDENTIFIQUE O TIPO DE PAINEL ANTES DE RESPONDER:

TIPO A) BOOK DE AGENTES / NEGOCIACAO / OFERTAS — possui COLUNA COM NOMES DE CORRETORAS
   (texto colorido: XP, BTG, Agora, Itau, Genial, Mirae, BGC Liquidez, JP Morgan...).
   -> preencha "agente" com o nome lido e marque "tem_nomes_agentes": true

TIPO B) SUPERDOM / PROFUNDIDADE / LIVRO AGREGADO — mostra APENAS colunas numericas
   (Qtde e Preco), SEM qualquer nome de corretora.
   -> preencha "agente" com exatamente "BOOK" e marque "tem_nomes_agentes": false

TIPO C) TIMES & TRADES / ORDEM ORIGINAL / NEGOCIOS — tabela de execucoes com as colunas
   Data (ou Hora), Compradora, Valor (preco), Quantidade, Vendedora e Agressor.
   ESTE TIPO TAMBEM TEM NOMES DE CORRETORAS e DEVE ser usado para preencher os agentes.
   Como converter o TAPE em ofertantes:
   - Some a Quantidade por corretora na coluna Compradora -> vira "ofertantes_compra",
     usando como "preco" o preco medio (ou o preco mais frequente) dos negocios dela.
   - Some a Quantidade por corretora na coluna Vendedora -> vira "ofertantes_venda",
     do mesmo modo.
   - Ordene do MAIOR volume somado para o menor e devolva ate 5 de cada lado.
   - Ignore linhas cuja corretora esteja como "-" (nao identificada).
   - Conte tambem a coluna Agressor: se a maioria for "Vendedor", a agressao e vendedora;
     se for "Comprador", a agressao e compradora.
   - Marque "tem_nomes_agentes": true e "tipo_painel": "times_trades_ordem_original".
   - Preencha ainda "agressao_dominante" com "comprador", "vendedor" ou "equilibrado",
     e "agressao_compradora_pct" / "agressao_vendedora_pct" (0-100) com base na
     proporcao de linhas de cada agressor.

REGRAS:
- So escreva um nome de corretora se REALMENTE conseguir LER esse nome na imagem.
- Se o painel nao tiver coluna de nomes (TIPO B), use exatamente "BOOK".
- NUNCA use "Nao identificado", "Não identificado", "N/A", "?", "Unknown" ou "Desconhecido".
- preco e numero decimal (ex: 5088.5), qtde e numero inteiro (ex: 1500).
- Se a imagem estiver ilegivel ou vazia, retorne as listas vazias em vez de inventar."""}]

    # Envia ate 8 imagens REAIS. O contador anterior nao cortava nada (somava e
    # parava, mas o envio seguia com a lista inteira), e as posicoes vazias
    # ocupavam vaga na fatia [:8] — empurrando o Livro de Ofertas para fora.
    _lista_imgs = [i for i in ([img_agentes, img_tt, img_tt_oo] + list(imgs_extra or []))
                   if i is not None][:8]
    for img in _lista_imgs:
        if img is not None:
            # Book e tape: tabelas numericas toleram bem a compressao.
            b64 = imagem_para_b64(img, largura_max=1100, qualidade=70)
            partes.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}})

    content = chamar_openrouter(partes, temperature=0.0, timeout=45)
    if not content:
        return {
            "agente_agora": {"acao": "sem_dados", "preco_compra": 0.0, "preco_venda": 0.0, "qtde": 0, "obs": "Erro na leitura"},
            "agentes_ativos": [],
            "resumo_agentes": "Sem leitura de agentes."
        }

    parsed = extrair_json(content)
    if parsed:
        return parsed

    return {
        "agente_agora": {"acao": "sem_dados", "preco": 0, "qtde": 0, "obs": "IA nao retornou JSON"},
        "agentes_ativos": [], "ofertantes_compra": [], "ofertantes_venda": [],
        "liquidez_forte": [], "desalavancagem": {"detectada": False, "descricao": ""},
        "resumo_agentes": "Sem leitura de agentes."
    }



def analisar_fluxo_com_ia(img_SuperDom, img_tt):
    """Analisa SuperDom e T&T via IA. Aceita None em qualquer das imagens."""
    partes = [{"type": "text", "text": """Analise as imagens do SuperDom e/ou Times & Trades do Profit.
Responda apenas em JSON valido sem markdown.

Campos obrigatórios:
{
  "saldo_agressao": "numero ou descricao do saldo de agressão visível",
  "dominancia": "comprador/vendedor/neutro",
  "pressao_compradora": 0,
  "pressao_vendedora": 0,
  "vies_fluxo": "comprador/vendedor/neutro/indefinido",
  "liquidez_compra": "onde esta a MAIOR liquidez de compra. Formato obrigatorio: 'NOME_CORRETORA 1500 @ 5088.00'. Se o painel nao mostrar nomes, use 'BOOK'.",
  "liquidez_venda": "onde esta a MAIOR liquidez de venda. Formato obrigatorio: 'NOME_CORRETORA 1200 @ 5100.00'. Se o painel nao mostrar nomes, use 'BOOK'.",
  "liquidez_compra_agentes": [{"agente": "", "preco": 0.0, "qtde": 0}],
  "liquidez_venda_agentes": [{"agente": "", "preco": 0.0, "qtde": 0}],
  "ordens_escondidas": "sim/nao/indefinido — há indícios de ordens institucionais escondidas?",
  "nivel_liquidez_forte": 0.0,
  "resumo_fluxo": "texto objetivo do que você observa no fluxo e na liquidez"
}"""}]

    for img in [img_SuperDom, img_tt]:
        if img is not None:
            # Book e tape: tabelas numericas toleram bem a compressao.
            b64 = imagem_para_b64(img, largura_max=1100, qualidade=70)
            partes.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}})

    if len(partes) == 1:
        return {"saldo_agressao":"N/A","dominancia":"indefinido","pressao_compradora":0,
                "pressao_vendedora":0,"vies_fluxo":"indefinido",
                "resumo_fluxo":"SuperDom e T&T nao capturados."}

    content = chamar_openrouter(partes, temperature=0.0, timeout=40)
    if not content:
        return {"saldo_agressao":"Erro","dominancia":"indefinido","pressao_compradora":0,
                "pressao_vendedora":0,"vies_fluxo":"indefinido","resumo_fluxo":"Erro na leitura de fluxo."}

    parsed = extrair_json(content)
    if parsed:
        return parsed

    return {"saldo_agressao":"Erro","dominancia":"indefinido","pressao_compradora":0,
            "pressao_vendedora":0,"vies_fluxo":"indefinido","resumo_fluxo":"Erro na leitura de fluxo."}


# =========================
# ANALISE COM IA
# =========================
def analisar_com_ia(img, dados_tela, contexto, fechamento_ant, ignorar_macro):
    macro = ler_dados_macro()
    buf=BytesIO(); img.save(buf,format="JPEG")
    b64=base64.b64encode(buf.getvalue()).decode()

    macro_bloco = ""
    if not ignorar_macro:
        macro_bloco = f"""
DADOS MACRO:
- DXY: {macro.get('DXY')} | EWZ: {macro.get('EWZ')} | USDBRL: {macro.get('USDBRL')}
- PTAX: {macro.get('PTAX')} | VIX: {macro.get('VIX')} | SPY: {macro.get('SPY')}
- QQQ: {macro.get('QQQ')} | TLT: {macro.get('TLT')} | GLD: {macro.get('GLD')} | Petroleo: {macro.get('CL_OIL')}
- Noticias: {macro.get('noticias')}
VIES DIA ANTERIOR: {fechamento_ant.get('vies','indefinido') if fechamento_ant else 'indefinido'}
"""
    prompt = f"""
Voce e uma IA de apoio para leitura de mercado.
Nao altere os numeros extraidos. A decisao final sera tomada pelo sistema.
Use a imagem apenas como confirmacao visual.

DADOS DA TELA:
{json.dumps(dados_tela, ensure_ascii=False)}

LEITURA OBJETIVA DO SISTEMA:
{json.dumps({k:v for k,v in contexto.items() if k not in ['validacao']}, ensure_ascii=False)}
{macro_bloco}

Responda apenas em JSON valido:
{{
  "confirmacao_visual": "texto",
  "auditoria_completa": "texto",
  "status_tt": "texto"
}}
"""
    partes = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]

    content = chamar_openrouter(partes, temperature=0.1, timeout=40)
    if not content:
        return {"confirmacao_visual":"Erro.","auditoria_completa":st.session_state.get("ultimo_erro_ia", "Falha na IA."),"status_tt":""}

    parsed = extrair_json(content)
    if parsed is None:
        return {"confirmacao_visual":"N/A","auditoria_completa":"IA invalido.","status_tt":""}

    return {"confirmacao_visual":parsed.get("confirmacao_visual",""),"auditoria_completa":parsed.get("auditoria_completa",""),"status_tt":parsed.get("status_tt","")}


# =========================
# EXECUCAO
# =========================
def executar_analise():
    ignorar_macro = st.session_state.modo_replay and not st.session_state.usar_macro_no_replay
    img, msg = capturar_janela()
    if img is None:
        st.session_state.ultimo_diagnostico = msg
        return None, msg

    dados_tela = extrair_dados_tela(img, st.session_state.modo_replay)
    if not dados_tela:
        st.session_state.ultimo_diagnostico = "Nao foi possivel extrair dados da tela."
        return img, msg

    # Modo replay: o relogio LIDO DA TELA do Profit tem prioridade absoluta.
    # O campo manual so e usado quando a IA nao conseguiu ler o relogio.
    if st.session_state.modo_replay:
        _hora_tela = str(dados_tela.get("hora_replay") or "").strip()
        _data_tela = str(dados_tela.get("data_replay") or "").strip()

        # valida o que veio da tela (formato HH:MM ou HH:MM:SS)
        _hora_valida = bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", _hora_tela))
        _data_valida = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", _data_tela) or re.match(r"^\d{2}/\d{2}/\d{4}$", _data_tela))

        if _hora_valida:
            # normaliza para HH:MM:SS
            _p = _hora_tela.split(":")
            _hh = f"{int(_p[0]):02d}:{int(_p[1]):02d}:{int(_p[2]) if len(_p) > 2 else 0:02d}"
            dados_tela["hora_replay"] = _hh
            dados_tela["hora_replay_origem"] = "tela"
            # sincroniza o campo manual com o que esta na tela (sem os segundos)
            _set_state("replay_hora", _hh[:5])
            _set_state("replay_seq", st.session_state.get("replay_seq", 0) + 1)
        else:
            dados_tela["hora_replay"] = st.session_state.replay_hora
            dados_tela["hora_replay_origem"] = "manual"

        if _data_valida:
            if "/" in _data_tela:
                _d, _m, _a = _data_tela.split("/")
                _data_tela = f"{_a}-{_m}-{_d}"
            dados_tela["data_replay"] = _data_tela
            _set_state("replay_data", _data_tela)
        else:
            dados_tela["data_replay"] = st.session_state.replay_data

    st.session_state.ultimos_dados_tela = dados_tela
    try:
        with open(DADOS_TELA_JSON,"w",encoding="utf-8") as f: json.dump(dados_tela,f,ensure_ascii=False,indent=2)
    except Exception: pass

    preco = num(dados_tela.get("preco_atual")); vwap = num(dados_tela.get("vwap"))
    ajuste = num(dados_tela.get("ajuste")); mm9 = num(dados_tela.get("mm9"))
    mm20 = num(dados_tela.get("mm20")); mm50 = num(dados_tela.get("mm50"))
    mm200 = num(dados_tela.get("mm200")); maxima = num(dados_tela.get("maxima"))
    minima = num(dados_tela.get("minima")); ptax_tela = num(dados_tela.get("ptax"))

    # Captura SuperDom, Times & Trades, Livro de Ofertas e Agentes
    img_sd, msg_sd_exec = capturar_SuperDom()
    img_tt2, msg_tt_exec = capturar_times_trades()
    img_livro, msg_livro_exec = capturar_livro_ofertas()
    img_agentes, msg_agentes_exec = capturar_agentes()

    # Guarda logs no session_state para exibicao no diagnóstico
    st.session_state["log_captura_SuperDom"] = msg_sd_exec
    st.session_state["log_captura_tt"] = msg_tt_exec
    st.session_state["log_captura_livro"] = msg_livro_exec
    st.session_state["log_captura_agentes"] = msg_agentes_exec

    # Análise de agentes (Agora, XP, BTG etc) — usa painel de agentes + T&T
    # Captura extra: T&T na aba Ordem Original (para análise cruzada)
    img_tt_oo, msg_tt_oo = capturar_times_trades_ordem_original()
    st.session_state["log_captura_tt_oo"] = msg_tt_oo

    # Envia TRÊS imagens à IA de agentes: Negócios (T&T padrão) + Ordem Original + Painel de Agentes
    # Captura TODAS as janelas do Profit — a IA identifica qual e qual.
    # Resolve o caso em que Ofertas/Negociacao sao ABAS dentro de janelas "WDOU26".
    _todas = capturar_todas_janelas_profit(max_janelas=6)
    st.session_state["log_captura_todas"] = (
        f"{len(_todas)} janelas capturadas: " +
        ", ".join(f"{j['titulo'][:22]} ({j['largura']}x{j['altura']})" for j in _todas)
    ) if _todas else "Nenhuma janela do Profit capturada."

    # O Livro de Ofertas e a UNICA janela com a coluna de corretora por preco.
    # Ele era capturado acima e usado so como fallback de fluxo: nunca chegava
    # a IA de agentes. Agora entra na frente das demais janelas na fila.
    _imgs_extra = ([img_livro] if img_livro is not None else []) + [j["img"] for j in _todas]
    agentes_info = analisar_agentes_com_ia(img_agentes, img_tt2, img_tt_oo, imgs_extra=_imgs_extra)
    st.session_state["ultimos_agentes"] = agentes_info

    # Se SuperDom falhou mas o Livro veio, usa o Livro como fonte de fluxo
    img_fluxo_book = img_sd if img_sd is not None else img_livro

    # Fallback: se tudo falhar, usa a imagem principal (IA extrai o que estiver visivel nela)
    if img_fluxo_book is None and img_tt2 is None:
        fluxo = analisar_fluxo_com_ia(img, None)
        st.session_state["fonte_fluxo"] = "janela_principal (fallback)"
    else:
        fluxo = analisar_fluxo_com_ia(img_fluxo_book, img_tt2)
        _fontes = []
        if img_sd is not None: _fontes.append("SuperDom")
        if img_livro is not None and img_sd is None: _fontes.append("Livro")
        if img_tt2 is not None: _fontes.append("T&T")
        st.session_state["fonte_fluxo"] = " + ".join(_fontes) if _fontes else "principal"
    # Injeta leitura de fluxo nos dados da tela
    dados_tela["status_fluxo"]      = fluxo.get("resumo_fluxo", dados_tela.get("status_fluxo",""))
    dados_tela["vies_fluxo"]        = fluxo.get("vies_fluxo","indefinido")
    dados_tela["dominancia_fluxo"]  = fluxo.get("dominancia","indefinido")
    dados_tela["saldo_agressao"]    = fluxo.get("saldo_agressao","")
    dados_tela["pressao_compradora"]= fluxo.get("pressao_compradora",0)
    dados_tela["pressao_vendedora"] = fluxo.get("pressao_vendedora",0)

    fech_ant = None if ignorar_macro else ler_fechamento_anterior()
    contexto = classificar_contexto(dados_tela, fech_ant, ignorar_macro)
    ia = analisar_com_ia(img, dados_tela, contexto, fech_ant, ignorar_macro)
    st.session_state['ultima_auditoria_ia'] = ia.get("auditoria_completa", "")

    est = contexto["estrategia"]; acao = contexto["acao_objetiva"]
    niveis = calcular_fibonacci(preco, acao if acao in ["compra","venda"] else "compra", est,
                                dados_tela=dados_tela, agentes_info=agentes_info, fechamento_ant=fech_ant)
    alvo = niveis["alvo"]; stop = niveis["stop"]
    pot_g = abs(alvo-preco); pot_p = abs(stop-preco)
    rr = round(pot_g/pot_p,2) if pot_p>0 else 0

    pe = ESTRATEGIAS[est]
    # VWAP ausente (nao lido da tela) NAO pode reprovar o gatilho.
    # Com 999 o requisito de margem falhava sempre e travava COMPRA score 7 em BLOQUEADO.
    dist_v = abs(preco - vwap) if vwap > 0 else 0.0
    contexto["vwap_ausente"] = vwap <= 0
    # Flexibilizado: só exige direção definida e margem VWAP.
    # RR baixo NÃO bloqueia mais — vira aviso.
    # Conflito, exaustão e volume fraco vêm do contexto.
    # ==== MOTOR DE DECISAO (AutoProTradingDecisionEngine) ====
    _acao_pret = acao.upper() if acao in ["compra","venda"] else "ESPERA"
    _dist_of = _calcular_distancia_maior_ofertante(preco, agentes_info, _acao_pret)
    _saldo_ag_pct = _calcular_saldo_agressao_pct(agentes_info)
    # ---- AJUSTE 3: book congelado ou fora de preco nao pesa no score ----
    if not contexto.get("book_valido", True):
        _saldo_ag_pct = 50.0
        contexto["saldo_agressao_invalidado"] = True
    _score_original = contexto["score"]
    _score_ponderado = DECISION_ENGINE.calcular_score_ponderado(
        score_atual=_score_original,
        distancia_ofertante=_dist_of,
        saldo_agressao_pct=_saldo_ag_pct,
        regime_tendencia=contexto.get("regime",""),
        acao_pretendida=_acao_pret,
    )
    contexto["score_ponderado"] = _score_ponderado
    contexto["score_original"] = _score_original
    contexto["distancia_maior_ofertante"] = _dist_of
    contexto["saldo_agressao_pct"] = _saldo_ag_pct
    # Atualiza o score do contexto com o ponderado para o resto do fluxo
    contexto["score"] = _score_ponderado

    # Avaliação do motor sobre exaustão em extremidade
    _dm = {
        "preco_atual": preco,
        "minima_dia": num(dados_tela.get("minima", 0)),
        "maxima_dia": num(dados_tela.get("maxima", 0)),
    }
    _avaliacao_engine = DECISION_ENGINE.avaliar_gatilho(_dm)
    contexto["engine_status"] = _avaliacao_engine["status"]
    contexto["engine_motivo"] = _avaliacao_engine["motivo"]

    req_ok = (
        acao in ["compra","venda"]
        and dist_v <= pe["margem_vwap"]
        and not contexto.get("conflito", False)
        and not contexto.get("exaustao_topo", False)
        and not contexto.get("exaustao_fundo", False)
        and contexto.get("volume_ok", True)
        and contexto["score"] >= contexto["score_minimo_usado"]
        and _avaliacao_engine["status"] == "APROVADO"
    )
    rr_baixo = rr < pe["rr_minimo"] and rr > 0

    # ---- AJUSTE 2: liberar gatilho com score alinhado ao momentum ou rompimento ----
    _mom_ctx = str(contexto.get("momentum", "neutro"))
    _score_ok = contexto["score"] >= contexto["score_minimo_usado"]
    # Score 7 nao teve UM acerto em 6 tentativas (-18,2 pts): confluencia total
    # significa movimento ja maduro. Teto operacional em 6.
    if contexto["score"] >= 7:
        # Score 7 com exaustao lida a favor da reversao nao e movimento maduro:
        # rebaixa em vez de vetar cego (mesma logica do otimizador de indicadores).
        if contexto.get("reversao_extremo") and contexto.get("absorcao_favoravel"):
            contexto["score_saturado"] = False
        else:
            _score_ok = False
            contexto["score_saturado"] = True
    _mom_alinhado = ((acao == "compra" and _mom_ctx in ("alta", "alta_forte")) or
                     (acao == "venda" and _mom_ctx in ("baixa", "baixa_forte")))
    _libera_momentum = (acao in ("compra", "venda") and _score_ok and _mom_alinhado
                        and not contexto.get("conflito", False)
                        and contexto.get("volume_ok", True)
                        and _avaliacao_engine["status"] in ("APROVADO", "ESPERA"))
    # Rompimento acertou 2 de 10: deixa de liberar entrada por conta propria.
    _libera_rompimento = False
    # ---- ANTI-OVERTRADING: um sinal por lado por candle ----
    _hc_now = st.session_state.get("hist_candles", [])
    _candle_atual = _hc_now[0].get("inicio", "") if _hc_now else ""
    _ult = st.session_state.get("ultimo_sinal_armado", {}) or {}
    _repetido = (
        req_ok
        and _ult.get("tipo") == acao
        and _ult.get("candle") == _candle_atual
        and _candle_atual != ""
        and abs(num(_ult.get("preco", 0)) - preco) < 3.0
    )
    if _repetido:
        req_ok = False
        contexto["motivo_bloqueio_repeticao"] = "Sinal já armado neste candle para o mesmo lado."

    if not req_ok and (_libera_momentum or _libera_rompimento):
        req_ok = True
        contexto["motivo_liberacao"] = ("Liberado por rompimento do candle anterior" if _libera_rompimento
                                        else f"Liberado por momentum {_mom_ctx} alinhado (score {contexto['score']}/{contexto['score_minimo_usado']})")

    if contexto.get("score_saturado") and acao in ("compra", "venda"):
        sg = "ESPERA"
    elif acao == "espera" or contexto.get("conflito", False):
        sg = "ESPERA"
    elif req_ok:
        sg = "ARMADO"
        st.session_state["ultimo_sinal_armado"] = {
            "tipo": acao, "preco": preco, "candle": _candle_atual,
        }
    else:
        sg = "BLOQUEADO"

    # ---- GATEKEEPER DE TRAVAS: avalia ANTES de falar, e agora REBAIXA o sinal ----
    # Antes so rodava na hora de montar o CSV: registrava "passaria bloqueado"
    # e o gatilho seguia ARMADO. Uma trava que nao altera o sg nao e trava.
    _gk = colunas_gatekeeper(contexto, dados_tela, preco)
    if sg == "ARMADO" and _gk.get("GatekeeperPermitido") == "nao":
        sg = "BLOQUEADO"
        _mgk = str(_gk.get("GatekeeperStatus", "Gatekeeper bloqueou"))
        contexto["motivo_bloqueio_gatekeeper"] = _mgk
        _fg = list(contexto.get("falta_para_gatilho", []) or [])
        _fg.insert(0, _mgk)
        contexto["falta_para_gatilho"] = _fg
        st.session_state["ultimo_sinal_armado"] = _ult or {}

    # ---- Alerta de mudanca brusca de tendencia ----
    _mudou, _desc_mud, _tipo_mud = detectar_mudanca_brusca(contexto, dados_tela)
    if _mudou:
        st.session_state["ultima_mudanca_brusca"] = f"{datetime.now().strftime('%H:%M:%S')} — {_desc_mud}"
        if st.session_state.get("som_mudanca_brusca", True):
            disparar_alarme(f"Atenção. Mudança brusca. {texto_para_voz(_desc_mud)[:110]}", tipo=_tipo_mud)

    # ---- EXECUCAO REAVALIADA COM O STATUS REAL DO GATILHO ----
    # Precisa vir aqui: sg e o gatekeeper acabaram de ser definidos. Rodar antes
    # deixava ExecucaoLiberada travada em "nao" mesmo com gatilho ARMADO.
    try:
        contexto = reavaliar_execucao(
            contexto, status_gatilho=sg,
            gatekeeper_permitido=_gk.get("GatekeeperPermitido", "sim"))
    except Exception:
        pass

    # ---- INDICACAO UNIFICADA: calculada ANTES do audio ----
    # Ordem antiga: audio "execute compra" -> veredito "aguardar". Duas ordens
    # diferentes na mesma leitura, e a voz saia primeiro. Agora o veredito vem
    # antes e o audio fala a MESMA conclusao que a tela mostra.
    contexto["_sg_atual"] = sg
    contexto_fluxo = {
        "agressao_pct": num(contexto.get("agressao_pct_leitura", contexto.get("saldo_agressao_pct", 50.0))),
        "vies_fluxo_lido": str(contexto.get("vies_fluxo_lido", "indefinido")),
        "tendencia_fluxo": str(contexto.get("tendencia_fluxo", "neutro")),
        "fluxo_direcional": bool(contexto.get("book_valido", False)),
    }
    _veredito = consolidar_veredito(contexto, _desc_mud, _mudou, contexto_fluxo=contexto_fluxo)

    # ---- AUDIO ALINHADO AO VEREDITO ----
    _vdir  = str(_veredito.get("direcao", "indefinida"))
    _vconv = int(num(_veredito.get("convicao", 0)))
    _vsug  = str(_veredito.get("acao_sugerida", "aguardar"))
    _alvo_fala = niveis.get("alvo", 0)
    _audio_divergente = "nao"
    _audio_txt = ""

    if sg == "ARMADO" and _vdir == acao and _vconv >= 55:
        _audio_txt = (f"Gatilho armado. {acao.capitalize()} em {preco:.0f}. "
                      f"Alvo {_alvo_fala:.0f}. Convicção {_vconv} por cento.")
        disparar_alarme(_audio_txt,
                        tipo="gatilho_compra" if acao == "compra" else "gatilho_venda")
    elif sg == "ARMADO":
        # Gatilho armou mas o conjunto das fontes nao confirma: avisa a divergencia
        # em vez de mandar executar. Som de aviso, nao som de gatilho.
        _audio_divergente = "sim"
        _motivo_div = (f"indicação aponta {_vdir}" if _vdir != acao
                       else f"convicção de apenas {_vconv} por cento")
        _audio_txt = (f"Atenção. Gatilho de {acao} armado, mas {_motivo_div}. "
                      f"Sugestão: {_vsug}. Confira antes de executar.")
        disparar_alarme(_audio_txt, tipo="aviso")
    elif _vconv >= 55 and _vdir in ("compra", "venda"):
        _audio_txt = f"Sem gatilho. Indicação de {_vdir}, convicção {_vconv} por cento."

    contexto["audio_divergente"] = _audio_divergente
    contexto["audio_texto"] = _audio_txt
    st.session_state["ultimo_veredito"] = _veredito
    # Contexto final da leitura, consumido pela aba Decisao Rapida. Sem isso a
    # aba lia uma chave inexistente e nunca mostrava nada.
    st.session_state["ultimo_contexto"] = contexto
    contexto["veredito_direcao"] = _veredito["direcao"]
    contexto["veredito_convicao"] = _veredito["convicao"]
    contexto["veredito_fontes"] = _veredito["fontes"]
    contexto["veredito_acao"] = _veredito["acao_sugerida"]

    if st.session_state.registrar_fechamento_ativo:
        mac = ler_dados_macro()
        salvar_fechamento_dia(preco,ajuste,vwap,num(mac.get("DXY")),num(mac.get("EWZ")),num(mac.get("VIX")))

    evento = ts_evento(dados_tela)
    mac = ler_dados_macro()
    val = calcular_pct(acao.upper(),preco,alvo,stop,maxima,minima)

    _falta_diag = " | ".join(contexto.get("falta_para_gatilho",[])) or "OK"
    diag = (f"{sg}: {acao.upper()} a {preco:.2f} | Est: {est} | Regime: {contexto['regime']} | "
            f"Vies ant: {contexto['vies_anterior']} | Alvo: {alvo:.2f} | Stop: {stop:.2f} | RR: {rr:.2f}"
            + (" ⚠️RR_BAIXO" if rr_baixo else "") + f" | "
            f"Score: {contexto['score']}/{contexto['score_minimo_usado']} | Limiar: {contexto['limiar']}% | "
            f"Padrao: {contexto.get('padrao_candle','')} | Vol: {contexto.get('volume_atual',0)} | "
            f"Faltas: {_falta_diag} | "
            f"Acerto: {val['PctAcerto']:.1f}% | Perda: {val['PctPerda']:.1f}% | "
            f"Fluxo: {ia['status_tt']} | Auditoria: {ia['auditoria_completa']}")

    registro = {
        "DataEvento": evento,
        "DataRegistro": (evento if st.session_state.modo_replay else datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "HoraReplayOrigem": str(dados_tela.get("hora_replay_origem", "manual")),
        "MudancaBrusca": "sim" if _mudou else "nao",
        "DescMudancaBrusca": str(_desc_mud)[:200],
        "DataAnaliseReal": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ModoReplay":"sim" if st.session_state.modo_replay else "nao",
        "MacroNoReplay":"sim" if st.session_state.usar_macro_no_replay else ("nao" if st.session_state.modo_replay else "sim"),
        "Estrategia":est,"Regime":contexto["regime"],"ViesAnterior":contexto["vies_anterior"],
        "StatusGatilho":sg,"Score":contexto["score"],"ScoreMin":contexto["score_minimo_usado"],
        "Limiar":contexto["limiar"],"DisparoAuto":bool(st.session_state.disparo_automatico),
        "Ativo":ativo_canonico(dados_tela.get("ativo","")),"Timeframe":dados_tela.get("timeframe",""),
        "BaseAlvo": str(niveis.get("base_alvo","fixo")),
        "BaseStop": str(niveis.get("base_stop","fixo")),
        "DistAlvoPts": niveis.get("dist_alvo", 0),
        "DistStopPts": niveis.get("dist_stop", 0),
        "ScoreOriginal": contexto.get("score_original", contexto.get("score",0)),
        "ScorePonderado": contexto.get("score_ponderado", contexto.get("score",0)),
        "DistanciaMaiorOfertante": contexto.get("distancia_maior_ofertante", 0),
        "SaldoAgressaoPct": contexto.get("saldo_agressao_pct", 50.0),
        "EngineStatus": contexto.get("engine_status", "N/A"),
        "EngineMotivo": contexto.get("engine_motivo", ""),
        "MaiorOfertanteCompra": (sorted(agentes_info.get("ofertantes_compra",[]) or [], key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[0].get("agente","BOOK") if agentes_info.get("ofertantes_compra") else ""),
        "MaiorOfertanteCompraQtde": (sorted(agentes_info.get("ofertantes_compra",[]) or [], key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[0].get("qtde",0) if agentes_info.get("ofertantes_compra") else 0),
        "MaiorOfertanteCompraPreco": (num(sorted(agentes_info.get("ofertantes_compra",[]) or [], key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[0].get("preco",0)) if agentes_info.get("ofertantes_compra") else 0),
        "MaiorOfertanteVenda": (sorted(agentes_info.get("ofertantes_venda",[]) or [], key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[0].get("agente","BOOK") if agentes_info.get("ofertantes_venda") else ""),
        "MaiorOfertanteVendaQtde": (sorted(agentes_info.get("ofertantes_venda",[]) or [], key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[0].get("qtde",0) if agentes_info.get("ofertantes_venda") else 0),
        "MaiorOfertanteVendaPreco": (num(sorted(agentes_info.get("ofertantes_venda",[]) or [], key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[0].get("preco",0)) if agentes_info.get("ofertantes_venda") else 0),
        "SaldoAgentes": str(agentes_info.get("saldo_agentes","")),
        "TemNomesAgentes": "sim" if agentes_info.get("tem_nomes_agentes", False) else "nao",
        "TipoPainelLido": str(agentes_info.get("tipo_painel","")),
        "Desalavancagem": "sim" if agentes_info.get("desalavancagem",{}).get("detectada",False) else "nao",
        "TopCompradores": ",".join(agentes_info.get("top_compradores",[])[:3]),
        "TopVendedores": ",".join(agentes_info.get("top_vendedores",[])[:3]),
        "EstrategiaEspecialTipo": contexto.get("estrategia_especial_tipo",""),
        "EstrategiaEspecialNome": contexto.get("estrategia_especial_nome",""),
        "Momentum": contexto.get("momentum",""),
        "DeltaPreco": contexto.get("delta_preco",0),
        "Delta3Leituras": contexto.get("delta_3",0),
        "PosRangeDia": contexto.get("pos_range",0),
        "PrevisaoDirecao": contexto.get("previsao_direcao",""),
        "PrevisaoProbAlta5": contexto.get("previsao_prob_alta_5",50),
        "PrevisaoProbAlta10": contexto.get("previsao_prob_alta_10",50),
        "PrevisaoProjecao5": contexto.get("previsao_projecao_5",0),
        "PrevisaoProjecao10": contexto.get("previsao_projecao_10",0),
        "PrevisaoConfianca": contexto.get("previsao_confianca",0),
        "VelocidadePtsMin": contexto.get("previsao_velocidade",0),
        "RompimentoDispara": "sim" if contexto.get("rompimento_dispara") else "nao",
        "RompimentoDirecao": contexto.get("rompimento_direcao",""),
        "RompimentoNivel": contexto.get("rompimento_nivel",0),
        "FluxoTendencia": contexto.get("fluxo_tendencia",""),
        "FluxoAbsorcao": contexto.get("fluxo_absorcao",""),
        "FluxoExaustao": contexto.get("fluxo_exaustao",""),
        "FluxoDesequilibrio": contexto.get("fluxo_desequilibrio",0),
        "FluxoDeltaAgressao": contexto.get("fluxo_delta_agressao",0),
        "FluxoValido": "sim" if contexto.get("fluxo_valido") else "nao",
        "AberturaObservacao": "sim" if contexto.get("abertura_em_observacao") else "nao",
        "AberturaGapPts": contexto.get("abertura_gap_pts",0),
        "AberturaTipo": contexto.get("abertura_tipo",""),
        "AberturaTendencia": contexto.get("abertura_tendencia",""),
        "AberturaAncora": contexto.get("abertura_ancora",""),
        "LotesVies": contexto.get("lotes_vies",""),
        "LotesForca": contexto.get("lotes_forca",0),
        "LotesDefesa": contexto.get("lotes_defesa",0),
        "LotesTeto": contexto.get("lotes_teto",0),
        "AlvoMaxAdaptativo": contexto.get("dist_alvo",0),
        "AlvoParcial": contexto.get("alvo_parcial",0),
        "BreakevenEm": contexto.get("breakeven_em",0),
        "TrailingDist": contexto.get("trailing_dist",0),
        "AmplitudeDia": contexto.get("amplitude_dia",0),
        "ZonaExaustaoPts": contexto.get("zona_exaustao_pts",0),
        "TetoRangeCompra": contexto.get("teto_range_compra",0),
        "ReversaoExtremo": "sim" if contexto.get("reversao_extremo") else "nao",
        "AbsorcaoFavoravel": "sim" if contexto.get("absorcao_favoravel") else "nao",
        "JanelaAbertura": "sim" if contexto.get("na_janela_abertura") else "nao",
        "MomentumForte": "sim" if contexto.get("momentum_forte_penalizado") else "nao",
        "ScoreSaturado": "sim" if contexto.get("score_saturado") else "nao",
        "VereditoDirecao": contexto.get("veredito_direcao",""),
        "VereditoConvicao": contexto.get("veredito_convicao",0),
        "VereditoFontes": contexto.get("veredito_fontes",0),
        "VereditoAcao": contexto.get("veredito_acao",""),
        "PullbackFavoravel": "sim" if contexto.get("pullback_favoravel") else "nao",
        "ZonaMorta": "sim" if contexto.get("zona_morta") else "nao",
        "EntradaTardia": "sim" if contexto.get("entrada_tardia") else "nao",
        "DistMM9Abs": contexto.get("dist_mm9_abs",0),
        "CorrigidoPorMomentum": "sim" if contexto.get("corrigido_por_momentum",False) else "nao",
        "PMI_EUA": contexto.get("pmi_valor"),
        "PMI_Vies": contexto.get("pmi_vies",""),
        "PadraoCandle": contexto.get("padrao_candle",""),
        "VolumeCandle": contexto.get("volume_atual",0),
        "ConviccaoPonderada": contexto.get("conviccao_ponderada", 0),
        "SugestaoUnificada": contexto.get("sugestao_acao", ""),
        "ExecucaoLiberada": contexto.get("execucao_liberada", "nao"),
        "EventoMacro": contexto.get("evento_macro", ""),
        "FaseMacro": contexto.get("fase_macro", "fora"),
        "MinutosMacro": contexto.get("minutos_macro", ""),
        "MacroVies": contexto.get("macro_vies", "neutro"),
        "MacroForca": contexto.get("macro_forca", "neutro"),
        "MacroDisponivel": "nao" if contexto.get("macro_indisponivel") else "sim",
        "MacroParcial": "sim" if contexto.get("macro_parcial") else "nao",
        "JanelaOperacional": (st.session_state.get("estado_janela") or {}).get("fase", "ativa"),
        "BollingerSuperior": contexto.get("bollinger_superior", 0.0),
        "BollingerCentral": contexto.get("bollinger_central", 0.0),
        "BollingerInferior": contexto.get("bollinger_inferior", 0.0),
        "BollingerEstado": contexto.get("bollinger_estado", ""),
        "BollingerPosicao": contexto.get("bollinger_posicao", -1.0),
        "BollingerEstreita": "sim" if contexto.get("bollinger_estreita") else "nao",
        "BollingerLarguraPct": contexto.get("bollinger_largura_pct", 0.0),
        "IFR": contexto.get("ifr", 50.0),
        "IFREstado": contexto.get("ifr_estado", ""),
        "IFRDivergencia": contexto.get("ifr_divergencia", ""),
        "ScalpDirecao": contexto.get("scalp_direcao", ""),
        "ScalpMotivo": contexto.get("scalp_motivo", ""),
        "ScalpVWAPPrimeiroToque": "sim" if contexto.get("scalp_vwap_primeiro") else "nao",
        "ScalpVWAPDist": contexto.get("scalp_vwap_dist", 0.0),
        "ScalpAjustePrimeiroToque": "sim" if contexto.get("scalp_ajuste_primeiro") else "nao",
        "ScalpAjusteDist": contexto.get("scalp_ajuste_dist", 0.0),
        "VolumeRelativo": contexto.get("volume_relativo", 0.0),
        "VolumePerfil": contexto.get("volume_perfil", ""),
        "RangeDiaMaxima": contexto.get("range_dia_maxima", 0.0),
        "RangeDiaMinima": contexto.get("range_dia_minima", 0.0),
        "RangeDiaAmplitude": contexto.get("range_dia_amplitude", 0.0),
        "RangeDiaValido": "sim" if contexto.get("range_dia_valido") else "nao",
        "AjusteOrigem": contexto.get("ajuste_origem", ""),
        "FaixaAtual": contexto.get("faixa_atual", ""),
        "FaixaAcao": contexto.get("faixa_acao", ""),
        "FaixaVerde": str(contexto.get("faixa_verde", "")),
        "FaixaAmarela": str(contexto.get("faixa_amarela", "")),
        "FaixaVermelha": str(contexto.get("faixa_vermelha", "")),
        "FaixaDataRef": contexto.get("faixa_data_ref", ""),
        "FaixaFonteRef": contexto.get("faixa_fonte_ref", ""),
        "FaixaMaximaAnt": contexto.get("faixa_maxima_ant", 0.0),
        "FaixaMinimaAnt": contexto.get("faixa_minima_ant", 0.0),
        "FaixaAjusteAnt": contexto.get("faixa_ajuste_ant", 0.0),
        "FaixaOrdenada": "sim" if contexto.get("faixa_ordenada") else "nao",
        "LimiteVetoMM9": contexto.get("limite_veto_mm9", 0.0),
        "IFRMotivo": contexto.get("ifr_motivo", ""),
        "TendenciaSobrepoeFluxo": "sim" if contexto.get("tendencia_sobrepoe_fluxo") else "nao",
        "OrigemCiclo": st.session_state.get("origem_ciclo_atual", "ciclo_5min"),
        "MacroFontes": json.dumps(contexto.get("macro_fontes", {}), ensure_ascii=False),
        "MotivoNaoExecutavel": contexto.get("motivo_nao_executavel", ""),
        "IndicesFavor": " | ".join(f'{i["rotulo"]}({i["peso"]:+d}/{i["acerto"]:.0f}%)'
                                  for i in contexto.get("indices_favor", [])),
        "IndicesContra": " | ".join(f'{i["rotulo"]}({i["peso"]:+d}/{i["acerto"]:.0f}%)'
                                   for i in contexto.get("indices_contra", [])),
        "AjustesOtimizacao": " | ".join(contexto.get("ajustes_otimizacao", [])),
        "VolumeStatus": contexto.get("volume_status", ""),
        "VolumeFinanceiro": contexto.get("volume_financeiro", 0),
        "VolumeFinanceiroTexto": contexto.get("volume_financeiro_texto", ""),
        "VolumeFinanceiroStatus": contexto.get("volume_financeiro_status", ""),
        "VolumeFinanceiroAcumulado": contexto.get("volume_financeiro_acumulado", 0),
        "VolumeDivergente": "sim" if contexto.get("volume_divergente") else "nao",
        **_gk,
        "AuditoriaIA": ia.get("auditoria_completa", ""),
        # ---- AUDITORIA: o audio concordou com a orientacao de execucao? ----
        "AudioDivergente": contexto.get("audio_divergente", ""),
        "AudioTexto": str(contexto.get("audio_texto", ""))[:200],
        # ---- AUDITORIA DE FLUXO: distingue leitura real de valor presumido ----
        "FluxoFonte": ("book_agentes" if str(dados_tela.get("tem_nomes_agentes","nao")) == "sim"
                       else "proxy_saldo_agentes"),
        "FluxoAgressaoReal": ("sim" if contexto.get("agressao_lida_real") else "nao"),
        "PosRangeValido": ("sim" if num(dados_tela.get("maxima",0)) > num(dados_tela.get("minima",0)) else "nao"),
        "Conflito": "sim" if contexto.get("conflito",False) else "nao",
        "InverteuPorCandle": "sim" if contexto.get("inverteu_por_candle",False) else "nao",
        "ReversaoPorExaustao": "sim" if contexto.get("reversao_por_exaustao",False) else "nao",
        "ExaustaoTopo": "sim" if contexto.get("exaustao_topo",False) else "nao",
        "ExaustaoFundo": "sim" if contexto.get("exaustao_fundo",False) else "nao",
        "RRBaixo": "sim" if rr_baixo else "nao",
        "ViesFluxo": fluxo.get("vies_fluxo","indefinido"),
        "DominanciaFluxo": fluxo.get("dominancia","indefinido"),
        "SaldoAgressao": str(fluxo.get("saldo_agressao","")),
        "PressaoCompradora": fluxo.get("pressao_compradora",0),
        "PressaoVendedora": fluxo.get("pressao_vendedora",0),
        "LiquidezCompra": descrever_liquidez_nomeada(agentes_info, fluxo, preco, "compra"),
        "LiquidezVenda": descrever_liquidez_nomeada(agentes_info, fluxo, preco, "venda"),
        "LiquidezCompraTextoIA": str(fluxo.get("liquidez_compra","")),
        "LiquidezVendaTextoIA": str(fluxo.get("liquidez_venda","")),
        "OrdensEscondidas": str(fluxo.get("ordens_escondidas","indefinido")),
        "NivelLiquidezForte": fluxo.get("nivel_liquidez_forte",0),
        "Tipo":acao.upper(),"PrecoEntrada":round(preco,2),
        "Abertura":num(dados_tela.get("abertura")),"Maxima":maxima,"Minima":minima,
        "Alvo":round(alvo,2),"Stop":round(stop,2),"PotGanho":round(pot_g,2),"PotPerda":round(pot_p,2),
        "RR":rr,"PontosFav":val["PontosFavoraveis"],"PontosContra":val["PontosContra"],
        "PctAcerto":val["PctAcerto"],"PctPerda":val["PctPerda"],"StatusEst":val["StatusEstimado"],
        "VWAP":round(vwap,2),"Ajuste":round(ajuste,2),"PTAX_Tela":round(ptax_tela,4) if ptax_tela>0 else "N/A",
        "MM9":round(mm9,2),"MM20":round(mm20,2),"MM50":round(mm50,2),"MM200":round(mm200,2),
        "ViesObjetivo":contexto["vies"],"Motivo":contexto["motivo_objetivo"],
        "StatusFluxo":ia["status_tt"],"ConfVisual":ia["confirmacao_visual"],
        "PMI_ISM": str(mac.get("PMI_ISM_SERVICOS","N/A")) if not ignorar_macro else "N/A",
        "PMI_Composto": str(mac.get("PMI_COMPOSTO","N/A")) if not ignorar_macro else "N/A",
        "DXY":mac.get("DXY") if not ignorar_macro else "N/A",
        "EWZ":mac.get("EWZ") if not ignorar_macro else "N/A",
        "PTAX_Bacen":mac.get("PTAX") if not ignorar_macro else "N/A",
        "VIX":mac.get("VIX") if not ignorar_macro else "N/A",
        "Noticias":mac.get("noticias") if not ignorar_macro else "Replay sem macro.",
        "Diag":diag,
    }

    salvo, erro = salvar_historico(registro)
    if not salvo: diag += f" | HIST: {erro}"
    st.session_state.ultimo_diagnostico = diag
    st.session_state.ultimo_status_gatilho = sg
    return img, msg


# =========================
# SINAL 9H
# =========================
def gerar_sinal_abertura():
    mac = ler_dados_macro()
    fech = ler_fechamento_anterior()
    vies = fech.get("vies","indefinido")
    dxy = num(mac.get("DXY"))
    ewz = num(mac.get("EWZ"))
    vix = num(mac.get("VIX"))

    sinais = []
    # DXY
    if dxy > 101: sinais.append(("🟢","DXY acima de 101 — dólar globalmente forte","compra"))
    elif dxy < 99: sinais.append(("🔴","DXY abaixo de 99 — dólar globalmente fraco","venda"))
    else: sinais.append(("🟡","DXY neutro","neutro"))
    # EWZ
    if ewz > 35: sinais.append(("🔴","EWZ acima de 35 — Brasil forte, pressão no dólar","venda"))
    elif ewz < 32: sinais.append(("🟢","EWZ abaixo de 32 — risco Brasil alto, dólar sobe","compra"))
    else: sinais.append(("🟡","EWZ neutro","neutro"))
    # VIX
    if vix > 20: sinais.append(("🟢","VIX acima de 20 — incerteza global, dólar tende a subir","compra"))
    elif vix < 13: sinais.append(("🔴","VIX abaixo de 13 — apetite a risco, dólar fraco","venda"))
    else: sinais.append(("🟡","VIX neutro","neutro"))
    # Vies anterior
    if vies=="comprador": sinais.append(("🟢",f"Vies do dia anterior: COMPRADOR","compra"))
    elif vies=="vendedor": sinais.append(("🔴",f"Vies do dia anterior: VENDEDOR","venda"))
    else: sinais.append(("🟡",f"Vies do dia anterior: NEUTRO/INDEFINIDO","neutro"))

    compras = sum(1 for s in sinais if s[2]=="compra")
    vendas  = sum(1 for s in sinais if s[2]=="venda")

    if compras >= 3: direcao,emoji = "COMPRA","🟢"
    elif vendas >= 3: direcao,emoji = "VENDA","🔴"
    elif compras > vendas: direcao,emoji = "TENDENCIA COMPRA","🟡"
    elif vendas > compras: direcao,emoji = "TENDENCIA VENDA","🟡"
    else: direcao,emoji = "INDEFINIDO","⚪"

    return {"direcao":direcao,"emoji":emoji,"sinais":sinais,"dxy":dxy,"ewz":ewz,"vix":vix,"vies":vies}


# =========================
# REFRESH
# =========================
# Refresh ADAPTATIVO: 30 s no dia inteiro e 5 s apenas nos minutos ao redor de
# um anuncio da agenda. A chave inclui o intervalo para o componente reiniciar
# quando o regime muda. O ciclo de analise segue travado em 300 s mais abaixo.
_refresh_ms = intervalo_refresh_atual()
st.session_state["refresh_ms_atual"] = _refresh_ms
count = st_autorefresh(interval=_refresh_ms, key=f"refresh_auto_{_refresh_ms}")
agora = time.time()
# A coleta macro tem relogio proprio de 300 s e respeita o cache por indicador
# (PTAX 1 h, cotacoes 15 min, PMI 6 h). Nunca roda em todo rerun: era isso que
# deixava o app ocupado sem nunca terminar de desenhar o painel.
if agora - st.session_state.ultimo_macro_update > INTERVALO_MACRO_SEGUNDOS:
    st.session_state.ultimo_macro_update = agora   # marca ANTES de buscar
    try:
        coletar_dados_macro()
    except Exception:
        pass


# =========================
# PROFUNDIDADE DE BOOK POR AGENTE + GUARDA DE VOLUME + PAINEL DE COMANDO
# =========================
VOLUME_MINIMO_SAUDAVEL = 15000   # abaixo disso a leitura nao sustenta gatilho
VOLUME_IDEAL           = 25000   # a partir daqui o historico mostra vantagem real


def _agente_limpo(nome):
    """Devolve '' quando nao ha nome real de corretora."""
    if not nome:
        return ""
    n = str(nome).strip()
    ruins = ["nao identificado", "não identificado", "n/a", "?", "unknown",
             "desconhecido", "-", "", "none", "null", "agregado",
             "book", "book (agregado)", "superdom", "livro"]
    if n.lower() in ruins:
        return ""
    return n[:22]


def _agente_do_tape(ag, lado, preco):
    """SuperDOM nao tem nome de corretora: tenta nomear o nivel pelo Times & Trades."""
    for item in (ag.get("liquidez_forte", []) or []):
        tipo = str(item.get("tipo", "")).lower()
        if tipo == ("compra" if lado == "bid" else "venda"):
            if abs(num(item.get("preco", 0)) - preco) <= 0.5:
                nm = _agente_limpo(item.get("agente", ""))
                if nm:
                    return nm, "tape"
    fonte = ag.get("top_compradores" if lado == "bid" else "top_vendedores", []) or []
    for nm in fonte:
        nm = _agente_limpo(nm)
        if nm:
            return nm, "tape_dominante"
    return "", ""


def montar_escada_book(ag, preco_atual=0.0, max_niveis=6):
    """Une preco + quantidade + AGENTE de cada nivel do book.

    Retorna {"asks": [...], "bids": [...], "tem_nomes": bool, "fonte": str}
    Cada nivel: {"preco", "qtde", "agente", "origem", "dist"}
    """
    if not ag:
        return {"asks": [], "bids": [], "tem_nomes": False, "fonte": "sem_leitura"}

    ofc = list(ag.get("ofertantes_compra", []) or [])
    ofv = list(ag.get("ofertantes_venda", []) or [])

    # A IA pode devolver a escada completa em "niveis_book"
    for n in (ag.get("niveis_book", []) or []):
        item = {"agente": n.get("agente", "") or n.get("agente_tape", ""),
                "preco": num(n.get("preco", 0)), "qtde": int(num(n.get("qtde", 0)))}
        if str(n.get("lado", "")).lower().startswith("comp"):
            ofc.append(item)
        elif str(n.get("lado", "")).lower().startswith("vend"):
            ofv.append(item)

    # Fallback: reaproveita liquidez_forte quando as listas vieram vazias
    if not ofc and not ofv:
        for l in (ag.get("liquidez_forte", []) or []):
            item = {"agente": l.get("agente", ""), "preco": num(l.get("preco", 0)),
                    "qtde": int(num(l.get("qtde", 0)))}
            if str(l.get("tipo", "")).lower() == "compra":
                ofc.append(item)
            elif str(l.get("tipo", "")).lower() == "venda":
                ofv.append(item)

    tem_nomes = bool(ag.get("tem_nomes_agentes", False)) or \
        any(_agente_limpo(o.get("agente", "")) for o in (ofc + ofv))

    def _normalizar(lista, lado):
        saida = []
        for o in lista:
            pr = num(o.get("preco", 0))
            qt = int(num(o.get("qtde", 0)))
            if pr <= 0 and qt <= 0:
                continue
            nome = _agente_limpo(o.get("agente", ""))
            origem = "book" if nome else ""
            if not nome:
                nome, origem = _agente_do_tape(ag, lado, pr)
            if not nome:
                nome, origem = "BOOK (agregado)", "superdom"
            saida.append({"preco": pr, "qtde": qt, "agente": nome, "origem": origem,
                          "dist": (pr - preco_atual) if preco_atual > 0 else 0.0})
        agrupado = {}
        for n in saida:
            k = round(n["preco"], 2)
            if k in agrupado:
                if n["qtde"] > agrupado[k]["qtde"]:
                    agrupado[k]["agente"] = n["agente"]
                    agrupado[k]["origem"] = n["origem"]
                agrupado[k]["qtde"] += n["qtde"]
            else:
                agrupado[k] = n
        saida = sorted(agrupado.values(), key=lambda x: x["preco"], reverse=True)
        return saida[:max_niveis] if lado == "ask" else saida[:max_niveis]

    asks = _normalizar(ofv, "ask")
    bids = _normalizar(ofc, "bid")
    fonte = "book_agentes" if tem_nomes else str(ag.get("tipo_painel", "superdom"))
    return {"asks": asks, "bids": bids, "tem_nomes": tem_nomes, "fonte": fonte}


def render_book_profundidade(ag, preco_atual=0.0, max_niveis=6):
    """Escada do book: Qtd | Preco | AGENTE | distancia do preco atual."""
    esc = montar_escada_book(ag, preco_atual, max_niveis)
    asks, bids = esc["asks"], esc["bids"]

    # Destaque com NOME do agente antes da escada completa.
    render_liquidez_nomeada(ag, st.session_state.get("ultimo_fluxo", {}), preco_atual)

    if not asks and not bids:
        st.info("A profundidade do book aparece aqui apos a primeira analise.")
        return esc

    maior = max([n["qtde"] for n in (asks + bids)] or [1]) or 1

    def _linha(n, lado):
        pct = max(6, int(100 * n["qtde"] / maior)) if maior else 6
        dist = n["dist"]
        cor_d = "#00e676" if dist > 0 else ("#ff5252" if dist < 0 else "#8892a4")
        tag = {"tape": " <small>· tape</small>",
               "tape_dominante": " <small>· tape</small>",
               "superdom": " <small>· sem nome</small>"}.get(n["origem"], "")
        qt_txt = f"{n['qtde']:,}".replace(",", ".")
        return (f'<div class="book-row {lado}">'
                f'<div class="qt">{qt_txt}</div>'
                f'<div class="pr">{n["preco"]:.2f}</div>'
                f'<div class="ag">{n["agente"]}{tag}'
                f'<div class="book-bar {lado}" style="width:{pct}%;margin-top:3px;"></div></div>'
                f'<div style="font-size:11px;text-align:right;color:{cor_d}">{dist:+.1f}</div>'
                f'</div>')

    html = ['<div class="book-wrap">']
    html.append(f'<div class="book-tit"><span>PROFUNDIDADE DO BOOK — PRECO x AGENTE</span>'
                f'<span class="pill {"ok" if esc["tem_nomes"] else "warn"}">'
                f'{"NOMES LIDOS NO BOOK" if esc["tem_nomes"] else "SUPERDOM — NOMES VIA TAPE"}'
                f'</span></div>')
    html.append('<div class="book-head"><div style="text-align:right">Qtd</div>'
                '<div>Preço</div><div>Agente / corretora</div>'
                '<div style="text-align:right">Dist.</div></div>')
    for n in asks:
        html.append(_linha(n, "ask"))
    html.append(f'<div class="book-mid"><span>PREÇO ATUAL</span>'
                f'<span class="p">{preco_atual:.2f}</span></div>')
    for n in bids:
        html.append(_linha(n, "bid"))
    if not esc["tem_nomes"]:
        html.append('<div style="font-size:11px;color:#ffd740;margin-top:8px;">'
                    'O painel lido é o SuperDOM (apenas números). Os nomes acima vêm do '
                    'Times &amp; Trades / Ordem Original. Para ver a corretora real por preço, '
                    'capture a janela <b>Book de Ofertas / Agentes</b>.</div>')
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)
    return esc


# ---------------------------------------------------------------------------
# MOTOR DE CONVICCAO PONDERADA
# Pesos medidos sobre 119 operacoes fechadas (base 69,7% de acerto medio).
# Cada indicador vale conforme o acerto historico QUE ELE ENTREGOU, nao
# conforme a intuicao. Indicador ruim nao e ignorado: e otimizado (so conta
# quando acompanhado da condicao que o salva) ou penalizado.
# ---------------------------------------------------------------------------
CONVICCAO_BASE = 50

TABELA_INDICADORES = [
    # (chave, rotulo, peso, acerto_historico, amostra)
    ("reversao_extremo_sim",  "Reversão no extremo do range",        +30, 100.0, 48),
    ("regime_pullback",       "Regime de pullback a favor",          +25, 100.0, 27),
    ("pullback_favoravel",    "Pullback confirmado no fluxo",        +18, 100.0, 18),
    ("fora_zona_morta",       "Fora da zona morta",                  +15,  96.0, 50),
    ("sem_absorcao_contra",   "Sem absorção contrária",              +12,  91.1, 45),
    ("veredito_forte",        "4+ leituras concordando",             +12,  90.0, 20),
    ("momentum_neutro",       "Momentum cadenciado (neutro)",        +12,  82.6, 46),
    ("sem_rompimento_seco",   "Entrada sem rompimento seco",         +12,  82.1, 78),
    ("score_ideal",           "Score na faixa ideal (4–5)",          +10,  81.8, 44),
    ("horario_bom",           "Horário de liquidez estrutural",       +8,  80.0, 79),


    # ---- penalidades medidas ----
    ("score_saturado_7",      "Score 7 — exaustão do movimento",     -40,   0.0,  6),
    ("janela_9h",             "Janela 09h–10h",                      -35,  20.0, 10),
    ("meio_do_range",         "Operando o meio do gráfico",          -25,  36.4, 11),
    ("momentum_alta_forte",   "Momentum forte CONTRA a entrada",     -22,  37.5, 16),
    ("momentum_alinhado",     "Momentum forte a favor da entrada",   +14,  70.0, 16),
    ("momentum_confirmado",   "Direção confirmada em 2+ leituras",   +10,  75.0, 20),

    ("rompimento_seco",       "Rompimento seco de candle",           -18,  46.3, 41),
    ("rr_esticado",           "Alvo esticado (RR 1.4–1.7)",          -12,  53.3, 15),


    ("regime_trend_puro",     "Tendência esticada sem pullback",      -8,  60.9, 92),
    ("confianca_maxima",      "Confiança 90% (euforia)",              -6,  66.7, 42),
    # ---- volatilidade e oscilacao (pesos iniciais, a calibrar com o log) ----
    ("bollinger_borda_favor", "Toque na banda de Bollinger a favor",  +16,  0.0,  0),
    ("bollinger_estreita",    "Bandas estreitas (consolidação)",       +8,  0.0,  0),
    ("ifr_divergencia",       "Divergência de IFR",                   +14,  0.0,  0),
    ("ifr_extremo_favor",     "IFR em extremo a favor da entrada",     +10,  0.0,  0),
    ("scalp_vwap_primeiro",   "1º toque do dia na VWAP",              +12,  0.0,  0),
    ("scalp_ajuste_primeiro", "1º toque do dia no Ajuste",            +12,  0.0,  0),
    ("volume_fraco_repique",  "Volume fraco na referência",            +6,  0.0,  0),
    ("bollinger_borda_contra", "Toque na banda CONTRA a entrada",     -16,  0.0,  0),
    ("ifr_extremo_contra",    "IFR em extremo contra a entrada",      -12,  0.0,  0),
    ("volume_rompimento",     "Volume de rompimento agressivo",       -14,  0.0,  0),
]
# Operacoes necessarias para um indicador valer o peso integral. Abaixo disso
# o peso e atenuado proporcionalmente — evidencia fraca pesa pouco.
AMOSTRA_MINIMA_PESO_CHEIO = 15

_MAPA_IND = {t[0]: t for t in TABELA_INDICADORES}


def _detectar_indicadores(ctx_res, dados_tela):
    """Marca quais indicadores estao presentes nesta leitura."""
    sim = lambda v: str(v).strip().lower() in ("sim", "true", "1", "yes")
    regime = str(ctx_res.get("regime", "")).lower()
    momentum = str(ctx_res.get("momentum", "")).lower()
    score = int(num(ctx_res.get("score", 0)))
    conf = num(ctx_res.get("previsao_confianca", 0))
    rr = num(ctx_res.get("rr", 0)) or num(ctx_res.get("RR", 0))
    fontes = int(num(ctx_res.get("veredito_fontes",
                     (st.session_state.get("ultimo_veredito", {}) or {}).get("fontes", 0))))
    try:
        hora_txt = str((dados_tela or {}).get("hora_replay", "") or datetime.now().strftime("%H:%M"))
        hora = int(hora_txt.split(":")[0])
    except Exception:
        hora = datetime.now().hour

    rev = sim(ctx_res.get("reversao_extremo"))
    pull_reg = "pullback" in regime
    pull_flx = sim(ctx_res.get("pullback_favoravel"))
    zmorta = sim(ctx_res.get("zona_morta"))
    absorve_contra = sim(ctx_res.get("absorcao_favoravel"))
    romp = bool((ctx_res.get("rompimento") or {}).get("dispara")) or sim(ctx_res.get("rompimento_dispara"))

    p = set()
    if rev: p.add("reversao_extremo_sim")
    else:   p.add("meio_do_range")
    if pull_reg: p.add("regime_pullback")
    elif regime.startswith("trend"): p.add("regime_trend_puro")
    if pull_flx: p.add("pullback_favoravel")
    if zmorta: p.add("zona_morta")
    else:      p.add("fora_zona_morta")
    if not absorve_contra: p.add("sem_absorcao_contra")
    if fontes >= 4: p.add("veredito_forte")
    if momentum == "neutro": p.add("momentum_neutro")

    # ---- MOMENTUM: penaliza a entrada CONTRA o movimento, nao a favor ----
    _mom_st = st.session_state.get("ultimo_momentum") or {}
    _dir_ctx = str(ctx_res.get("acao_pretendida", ctx_res.get("acao_objetiva", ""))).lower()
    _dist9_ctx = num(ctx_res.get("dist_mm9", 0))
    if _dist9_ctx <= 0:
        _p_ctx = num((dados_tela or {}).get("preco_atual", 0))
        _m9_ctx = num((dados_tela or {}).get("mm9", 0))
        _dist9_ctx = abs(_p_ctx - _m9_ctx) if (_p_ctx > 0 and _m9_ctx > 0) else 0.0
    _forte = momentum in ("alta_forte", "baixa_forte")
    _contra = ((momentum in ("alta_forte", "alta") and _dir_ctx == "venda") or
               (momentum in ("baixa_forte", "baixa") and _dir_ctx == "compra"))
    _a_favor = ((momentum in ("alta_forte", "alta") and _dir_ctx == "compra") or
                (momentum in ("baixa_forte", "baixa") and _dir_ctx == "venda"))
    if _forte and (_contra or _dist9_ctx >= LIMITE_DIST_MM9_ENTRADA):
        p.add("momentum_alta_forte")
    elif _forte and _a_favor:
        p.add("momentum_alinhado")
    if _mom_st.get("momentum_confirmado") and _a_favor:
        p.add("momentum_confirmado")
    if romp: p.add("rompimento_seco")
    else:    p.add("sem_rompimento_seco")
    if score == 7: p.add("score_saturado_7")
    elif score in (4, 5): p.add("score_ideal")
    if hora == 9: p.add("janela_9h")
    elif hora == 13: p.add("horario_13h")
    else: p.add("horario_bom")
    if rr and rr <= 1.2: p.add("rr_curto")
    elif 1.4 < rr <= 1.7: p.add("rr_esticado")
    if conf >= 90: p.add("confianca_maxima")
    elif conf >= 70: p.add("confianca_media")
    elif conf < 35: p.add("confianca_baixa")
    return p


def otimizar_indicadores_fracos(presentes, ctx_res):
    """Os indicadores de baixo acerto nao sao descartados: passam a valer
    somente quando a condicao que os resgata esta presente."""
    ajustes = []
    # 1) Rompimento seco: 46% isolado, mas util quando nasce num extremo.
    if "rompimento_seco" in presentes and "reversao_extremo_sim" in presentes:
        presentes.discard("rompimento_seco")
        presentes.add("sem_rompimento_seco")
        ajustes.append("Rompimento aceito: nasceu no extremo do range.")
    # 2) Tendencia esticada: so vale se houver pullback confirmado no fluxo.
    if "regime_trend_puro" in presentes and "pullback_favoravel" in presentes:
        presentes.discard("regime_trend_puro")
        presentes.add("regime_pullback")
        ajustes.append("Tendência revalidada: entrada no pullback, não na ponta.")
    # 3) Score 7 e exaustao: rebaixa para a faixa ideal em vez de vetar cego.
    if "score_saturado_7" in presentes and "reversao_extremo_sim" in presentes:
        presentes.discard("score_saturado_7")
        presentes.add("score_ideal")
        ajustes.append("Score 7 rebaixado: leitura de exaustão a favor da reversão.")
    # 4) Momentum alta_forte: perdoa quando ha absorcao a favor e volume real.
    if "momentum_alta_forte" in presentes and "sem_absorcao_contra" in presentes \
            and num(ctx_res.get("volume_candle_lido", 0)) >= VOLUME_IDEAL:
        presentes.discard("momentum_alta_forte")
        ajustes.append("Momentum forte aceito: volume real e sem absorção contrária.")
    # 5) Meio do range: exige pullback para nao virar liquidificador.
    if "meio_do_range" in presentes and "pullback_favoravel" in presentes:
        presentes.discard("meio_do_range")
        ajustes.append("Meio do range liberado: pullback dá referência de defesa.")
    # 6) Janela das 9h: -35 zerava qualquer leitura correta da abertura. A
    #    penalidade cai quando existe ancora — as mesmas duas condicoes que a
    #    propria janela ja exige para armar.
    if "janela_9h" in presentes and ("reversao_extremo_sim" in presentes
                                     or "pullback_favoravel" in presentes):
        presentes.discard("janela_9h")
        ajustes.append("Janela 09h liberada: entrada ancorada em pullback/reversão.")
    # 7) Momentum a favor e penalidade de momentum nunca coexistem.
    if "momentum_alinhado" in presentes:
        presentes.discard("momentum_alta_forte")
    return presentes, ajustes


def avaliar_conviccao(ctx_res, dados_tela):
    """Soma ponderada dos indicadores -> conviccao 0-100 e sugestao unificada."""
    presentes = _detectar_indicadores(ctx_res, dados_tela)
    presentes, ajustes = otimizar_indicadores_fracos(presentes, ctx_res)

    favor, contra, soma = [], [], 0
    for chave in presentes:
        t = _MAPA_IND.get(chave)
        if not t:
            continue
        _, rotulo, peso, acerto, amostra = t
        # ---- PESO PROPORCIONAL A AMOSTRA ----
        # Indicador com amostra pequena (ou zero, como Bollinger/IFR/Scalp
        # recem-criados) nao pode empurrar a conviccao com peso cheio: o peso
        # cresce junto com a evidencia, ate 15 operacoes.
        if amostra < AMOSTRA_MINIMA_PESO_CHEIO:
            peso = int(round(peso * (max(0, amostra) / float(AMOSTRA_MINIMA_PESO_CHEIO))))
            if peso == 0:
                continue
        soma += peso
        item = {"rotulo": rotulo, "peso": peso, "acerto": acerto, "amostra": amostra}
        (favor if peso > 0 else contra).append(item)

    favor.sort(key=lambda x: -x["peso"])
    contra.sort(key=lambda x: x["peso"])
    conviccao = int(max(0, min(100, CONVICCAO_BASE + soma)))

    direcao = str(ctx_res.get("acao_pretendida", ctx_res.get("acao_objetiva", "espera"))).lower()

    # ---- EXECUCAO DESACOPLADA DA CONVICCAO ----
    # Uma leitura em ESPERA aparecia com 100% e o log gravava "EXECUTAR" sem
    # gatilho armado. Executar passa a exigir as QUATRO condicoes juntas:
    # direcao valida + status ARMADO + score no minimo + gatekeeper liberado.
    _sg_res = str(ctx_res.get("status_gatilho", ctx_res.get("_sg_atual", ""))).strip().upper()
    _score_res = num(ctx_res.get("score", 0))
    _score_min_res = num(ctx_res.get("score_minimo_usado", ctx_res.get("score_min", 0)))
    _gk_res = str(ctx_res.get("gatekeeper_permitido",
                              ctx_res.get("GatekeeperPermitido", "sim"))).strip().lower()
    _armado_ok = _sg_res == "ARMADO"
    _score_ok = (_score_res >= _score_min_res) if _score_min_res > 0 else True
    _gk_ok = _gk_res != "nao"
    executavel = bool(direcao in ("compra", "venda") and _armado_ok and _score_ok and _gk_ok)

    _motivos_exec = []
    if not _armado_ok:
        _motivos_exec.append(f"gatilho em {_sg_res or 'ESPERA'}")
    if not _score_ok:
        _motivos_exec.append(f"score {int(_score_res)}/{int(_score_min_res)}")
    if not _gk_ok:
        _motivos_exec.append("gatekeeper bloqueou")
    _txt_exec = ", ".join(_motivos_exec) or "sem confirmação"

    # Sem gatilho armado a conviccao exibida e limitada: 100% deixa de existir
    # em leitura que o motor nao liberou.
    if not executavel:
        conviccao = int(min(conviccao, TETO_CONVICCAO_SEM_GATILHO))

    if direcao not in ("compra", "venda"):
        acao, cor, texto = "FORA", "#8892a4", "Sem direção definida — nada a fazer."
    elif conviccao >= 70 and executavel:
        acao, cor = ("EXECUTAR " + direcao.upper()), ("#00e676" if direcao == "compra" else "#ff5252")
        texto = f"Confluência forte ({conviccao}%) com gatilho armado — operar no tamanho cheio."
    elif conviccao >= 45 and executavel:
        acao, cor = ("MEIA POSIÇÃO " + direcao.upper()), "#ffd740"
        texto = f"Confluência parcial ({conviccao}%) — metade do lote e alvo curto."
    elif conviccao >= 45 and not executavel:
        acao, cor = ("AGUARDAR CONFIRMAÇÃO " + direcao.upper()), "#ffd740"
        texto = (f"Direção de {direcao} com {conviccao}% de convicção, porém sem execução "
                 f"liberada ({_txt_exec}) — não enviar ordem.")
    else:
        _mom_st = st.session_state.get("ultimo_momentum") or {}
        _mom_dir = str(_mom_st.get("momentum", ""))
        _alinhado = ((direcao == "compra" and _mom_dir in ("alta", "alta_forte")) or
                     (direcao == "venda" and _mom_dir in ("baixa", "baixa_forte")))
        if _mom_st.get("momentum_confirmado") and _alinhado:
            # Direcao certa bloqueada por TIMING nao e sinal errado: o correto e
            # aguardar a reaproximacao da MM9, nao zerar a leitura.
            acao, cor = ("AGUARDAR PULLBACK " + direcao.upper()), "#ffd740"
            texto = (f"Direção confirmada ({conviccao}%) mas entrada fora do preço — "
                     f"armar na reaproximação da MM9.")
        else:
            acao, cor = "NÃO OPERAR", "#ff5252"
            texto = f"Confluência fraca ({conviccao}%) — os pesos contra dominam a leitura."

    ctx_res["conviccao_ponderada"] = conviccao
    ctx_res["conviccao_bruta_ponderada"] = int(max(0, min(100, CONVICCAO_BASE + soma)))
    ctx_res["execucao_liberada"] = "sim" if executavel else "nao"
    ctx_res["motivo_nao_executavel"] = "" if executavel else _txt_exec
    ctx_res["indices_favor"] = favor
    ctx_res["indices_contra"] = contra
    ctx_res["ajustes_otimizacao"] = ajustes
    ctx_res["sugestao_acao"] = acao
    ctx_res["sugestao_cor"] = cor
    ctx_res["sugestao_texto"] = texto
    if conviccao < 45 and direcao in ("compra", "venda"):
        ctx_res["acao_pretendida"] = direcao
        ctx_res["acao_objetiva"] = "espera"
        ctx_res["status_gatilho"] = "ESPERA"
        faltas = list(ctx_res.get("falta_para_gatilho", []) or [])
        faltas.insert(0, f"Convicção ponderada em {conviccao}% — mínimo de 45%")
        ctx_res["falta_para_gatilho"] = faltas
    return ctx_res


def reavaliar_execucao(contexto, status_gatilho=None, gatekeeper_permitido=None):
    """Recalcula ExecucaoLiberada DEPOIS que o status do gatilho existe.

    O calculo original rodava dentro de avaliar_conviccao, antes de sg ser
    definido: lia sempre o estado anterior e gravava "gatilho em ESPERA" mesmo
    nas leituras ARMADAS. Esta funcao e a fonte unica de verdade da execucao e
    reescreve tambem a sugestao, para painel e log nunca divergirem.
    """
    if not isinstance(contexto, dict):
        return contexto

    sg = str(status_gatilho if status_gatilho is not None
             else contexto.get("status_gatilho", contexto.get("_sg_atual", ""))).strip().upper()
    gk = str(gatekeeper_permitido if gatekeeper_permitido is not None
             else contexto.get("gatekeeper_permitido", "sim")).strip().lower()

    direcao = str(contexto.get("acao_pretendida",
                               contexto.get("acao_objetiva", "espera"))).lower()
    score = num(contexto.get("score", 0))
    score_min = num(contexto.get("score_minimo_usado", contexto.get("score_min", 0)))

    armado_ok = sg == "ARMADO"
    score_ok = (score >= score_min) if score_min > 0 else True
    gk_ok = gk != "nao"
    executavel = bool(direcao in ("compra", "venda") and armado_ok and score_ok and gk_ok)

    motivos = []
    if not armado_ok:
        motivos.append(f"gatilho em {sg or 'ESPERA'}")
    if not score_ok:
        motivos.append(f"score {int(score)}/{int(score_min)}")
    if not gk_ok:
        motivos.append("gatekeeper bloqueou")
    txt = ", ".join(motivos) or "sem confirmação"

    # A conviccao volta a partir do valor BRUTO: o teto de 60% sem gatilho nao
    # pode ser aplicado duas vezes, senao a leitura armada herda o corte.
    conv = int(num(contexto.get("conviccao_bruta_ponderada",
                                contexto.get("conviccao_ponderada", 0))))
    if not executavel:
        conv = int(min(conv, TETO_CONVICCAO_SEM_GATILHO))

    if direcao not in ("compra", "venda"):
        acao, cor, texto = "FORA", "#8892a4", "Sem direção definida — nada a fazer."
    elif conv >= 70 and executavel:
        acao, cor = ("EXECUTAR " + direcao.upper()), ("#00e676" if direcao == "compra" else "#ff5252")
        texto = f"Confluência forte ({conv}%) com gatilho armado — operar no tamanho cheio."
    elif conv >= 45 and executavel:
        acao, cor = ("MEIA POSIÇÃO " + direcao.upper()), "#ffd740"
        texto = f"Confluência parcial ({conv}%) — metade do lote e alvo curto."
    elif executavel:
        # Gatilho armado com confluencia baixa: opera reduzido em vez de sumir.
        acao, cor = ("MEIA POSIÇÃO " + direcao.upper()), "#ffd740"
        texto = f"Gatilho armado com confluência de {conv}% — tamanho reduzido."
    elif conv >= 45:
        acao, cor = ("AGUARDAR CONFIRMAÇÃO " + direcao.upper()), "#ffd740"
        texto = (f"Direção de {direcao} com {conv}% de convicção, porém sem execução "
                 f"liberada ({txt}) — não enviar ordem.")
    else:
        _mom_st = st.session_state.get("ultimo_momentum") or {}
        _mom_dir = str(_mom_st.get("momentum", ""))
        _alinhado = ((direcao == "compra" and _mom_dir in ("alta", "alta_forte")) or
                     (direcao == "venda" and _mom_dir in ("baixa", "baixa_forte")))
        if _mom_st.get("momentum_confirmado") and _alinhado:
            acao, cor = ("AGUARDAR PULLBACK " + direcao.upper()), "#ffd740"
            texto = (f"Direção confirmada ({conv}%) mas entrada fora do preço — "
                     f"armar na reaproximação da MM9.")
        else:
            acao, cor = "NÃO OPERAR", "#ff5252"
            texto = f"Confluência fraca ({conv}%) — os pesos contra dominam a leitura."

    contexto["status_gatilho"] = sg or contexto.get("status_gatilho", "")
    contexto["gatekeeper_permitido"] = gk
    contexto["conviccao_ponderada"] = conv
    contexto["execucao_liberada"] = "sim" if executavel else "nao"
    contexto["motivo_nao_executavel"] = "" if executavel else txt
    contexto["sugestao_acao"] = acao
    contexto["sugestao_cor"] = cor
    contexto["sugestao_texto"] = texto
    return contexto


def render_ranking_indicadores():
    """Ranking historico completo — detalhe para analise."""
    linhas = []
    for chave, rotulo, peso, acerto, amostra in sorted(
            TABELA_INDICADORES, key=lambda t: -t[3]):
        cor = "#00e676" if acerto >= 80 else ("#ffd740" if acerto >= 65 else "#ff5252")
        larg = int(max(3, min(100, acerto)))
        linhas.append(
            f'<div style="display:grid;grid-template-columns:1fr 62px 58px 52px;gap:8px;'
            f'align-items:center;padding:5px 6px;font-size:12px;border-bottom:1px solid #1b2135;">'
            f'<div>{rotulo}<div style="background:#0e1117;border-radius:3px;height:5px;margin-top:3px;">'
            f'<div style="background:{cor};height:5px;width:{larg}%;border-radius:3px;"></div></div></div>'
            f'<div style="color:{cor};font-weight:700;text-align:right">{acerto:.1f}%</div>'
            f'<div style="color:#8892a4;text-align:right">n={amostra}</div>'
            f'<div style="color:{"#00e676" if peso > 0 else "#ff5252"};font-weight:700;'
            f'text-align:right">{peso:+d}</div></div>')
    st.markdown(
        '<div class="book-wrap"><div class="book-tit">'
        '<span>RANKING HISTÓRICO DOS INDICADORES</span>'
        '<span class="pill info">119 operações fechadas</span></div>'
        '<div style="display:grid;grid-template-columns:1fr 62px 58px 52px;gap:8px;'
        'font-size:10px;color:#7d879b;text-transform:uppercase;letter-spacing:1px;'
        'padding:0 6px 5px 6px;border-bottom:1px solid #232a45;">'
        '<div>Indicador</div><div style="text-align:right">Acerto</div>'
        '<div style="text-align:right">Amostra</div><div style="text-align:right">Peso</div></div>'
        + "".join(linhas) +
        '<div style="font-size:11px;color:#8892a4;margin-top:8px;">O peso é aplicado sobre '
        'a base de 50% para gerar a convicção ponderada da sugestão unificada.</div></div>',
        unsafe_allow_html=True)



# ---- VOLUME FINANCEIRO (barra abaixo do grafico) ----
# Ate aqui o sistema so lia volume em CONTRATOS. O financeiro e um segundo eixo:
# 5.000 contratos de WDO a 5.100 nao movimentam o mesmo dinheiro que 5.000 a 4.800,
# e e a barra abaixo do grafico que mostra isso.
VOLUME_MINIMO_OK   = 300.0   # contratos no candle. Piso unico usado no teste E na mensagem.
VOLUME_FORTE       = 1000.0
POS_RANGE_TETO_COMPRA = 88.0  # compra acima disso = topo do dia
POS_RANGE_PISO_VENDA  = 12.0  # venda abaixo disso = fundo do dia

VOLFIN_MINIMO_SAUDAVEL = 500_000_000.0    # R$ 500 mi na barra do periodo
VOLFIN_IDEAL           = 1_200_000_000.0  # R$ 1,2 bi - presenca institucional real


def parse_volume_financeiro(txt):
    """Converte '1,25 B' / '870 M' / '15.400' em float de reais. 0.0 se ilegivel."""
    if txt is None:
        return 0.0
    s = str(txt).strip().upper().replace("R$", "").strip()
    if not s:
        return 0.0
    mult = 1.0
    for suf, m in (("BI", 1e9), ("B", 1e9), ("MI", 1e6), ("M", 1e6), ("K", 1e3)):
        if s.endswith(suf):
            mult = m
            s = s[:-len(suf)].strip()
            break
    # formato brasileiro: ponto e milhar, virgula e decimal
    s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s) * mult
    except Exception:
        return 0.0


def formatar_volume_financeiro(v):
    v = float(v or 0)
    if v <= 0:
        return "nao lido"
    if v >= 1e9:
        return "R$ {:.2f} bi".format(v / 1e9)
    if v >= 1e6:
        return "R$ {:.0f} mi".format(v / 1e6)
    return "R$ {:,.0f}".format(v).replace(",", ".")


def aplicar_guarda_volume_financeiro(ctx_res, dados_tela):
    """Classifica o volume FINANCEIRO. Nao bloqueia sozinho: entra como
    componente de contexto. Bloquear por um campo recem-criado repetiria o erro
    de tratar campo ausente como sinal negativo."""
    dt = dados_tela or {}
    bruto = dt.get("volume_financeiro", "") or dt.get("volume_financeiro_barra", "")
    valor = parse_volume_financeiro(bruto)
    acum = parse_volume_financeiro(dt.get("volume_financeiro_acumulado", ""))

    ctx_res["volume_financeiro_texto"] = str(bruto or "")
    ctx_res["volume_financeiro"] = valor
    ctx_res["volume_financeiro_acumulado"] = acum

    if valor <= 0:
        ctx_res["volume_financeiro_status"] = "nao_lido"
        ctx_res["volume_financeiro_aviso"] = ""
    elif valor < VOLFIN_MINIMO_SAUDAVEL:
        ctx_res["volume_financeiro_status"] = "fraco"
        ctx_res["volume_financeiro_aviso"] = (
            "Volume financeiro de " + formatar_volume_financeiro(valor) +
            " - abaixo do piso institucional.")
    elif valor < VOLFIN_IDEAL:
        ctx_res["volume_financeiro_status"] = "medio"
        ctx_res["volume_financeiro_aviso"] = ""
    else:
        ctx_res["volume_financeiro_status"] = "forte"
        ctx_res["volume_financeiro_aviso"] = ""

    # Divergencia contratos x financeiro: muito contrato com pouco dinheiro e
    # giro de curtissimo prazo, nao posicionamento.
    _contratos = num(ctx_res.get("volume_candle_lido", 0))
    ctx_res["volume_divergente"] = bool(
        _contratos >= VOLUME_IDEAL and 0 < valor < VOLFIN_MINIMO_SAUDAVEL)
    if ctx_res["volume_divergente"]:
        ctx_res.setdefault("ajustes_otimizacao", []).append(
            "Volume em contratos alto com financeiro fraco - giro sem posicionamento.")
    return ctx_res

# ---- BLOCO BLINDADO CONTRA SUMIÇO DE DADOS E LINKS ----
def descrever_liquidez_nomeada(ag, fluxo, preco_atual=0.0, lado="compra", max_itens=3):
    """Monta a string de liquidez garantindo que NUNCA retorne vazio 
    se houver dados anteriores ou fallback disponível."""
    
    partes = []
    
    # Validação e extração segura da escada
    if ag and isinstance(ag, dict):
        esc = montar_escada_book(ag, preco_atual, max_niveis=8) or {}
        niveis = esc.get("bids") or esc.get("compras") if lado == "compra" else esc.get("asks") or esc.get("vendas")
        
        if not niveis:
            chave_ag = "ofertantes_compra" if lado == "compra" else "ofertantes_venda"
            niveis = ag.get(chave_ag, []) or []

        for n in (niveis or [])[:max_itens]:
            if not isinstance(n, dict):
                continue
            nome = str(n.get("agente") or n.get("corretora") or "BOOK").strip()
            pr = num(n.get("preco", 0))
            qt = num(n.get("qtde", n.get("quantidade", 0)))
            
            if qt > 0:
                if pr > 0 and preco_atual > 0:
                    dist = pr - preco_atual
                    partes.append(f"**{nome}** {int(qt)} @ {pr:.2f} (`{dist:+.1f}`)")
                elif pr > 0:
                    partes.append(f"**{nome}** {int(qt)} @ {pr:.2f}")
                else:
                    partes.append(f"**{nome}** {int(qt)}")

    if partes:
        return " | ".join(partes)

    # Fallback para o fluxo de IA se a escada falhar
    chave_fluxo = "liquidez_compra" if lado == "compra" else "liquidez_venda"
    txt_fluxo = (fluxo or {}).get(chave_fluxo, "")
    if txt_fluxo:
        return str(txt_fluxo)

    # Retorna um traço formatado em vez de string vazia para o bloco não sumir do layout
    return "N/D (Aguardando book...)"


def render_liquidez_nomeada(ag, fluxo, preco_atual=0.0):
    """Bloco de destaque protegido contra desaparecimento de componentes."""
    
    # Armazena no session_state para evitar que o painel suma se o tick vier vazio
    if "ultimo_compra_liq" not in st.session_state:
        st.session_state.ultimo_compra_liq = "Carregando..."
    if "ultimo_venda_liq" not in st.session_state:
        st.session_state.ultimo_venda_liq = "Carregando..."

    tem_nomes = bool((ag or {}).get("tem_nomes_agentes", False))
    rotulo = "GRANDE LIQUIDEZ - AGENTES" if tem_nomes else "GRANDE LIQUIDEZ - BOOK AGREGADO (sem nomes)"
    
    res_compra = descrever_liquidez_nomeada(ag, fluxo, preco_atual, "compra")
    res_venda = descrever_liquidez_nomeada(ag, fluxo, preco_atual, "venda")

    # Atualiza apenas se encontrou dados reais, mantendo o último válido se houver oscilação
    if "Aguardando" not in res_compra and "N/D" not in res_compra:
        st.session_state.ultimo_compra_liq = res_compra
    if "Aguardando" not in res_venda and "N/D" not in res_venda:
        st.session_state.ultimo_venda_liq = res_venda

    # Renderização visual limpa no Streamlit
    st.markdown(
        f"### {rotulo}  \n"
        f"🟩 **Compra:** {st.session_state.ultimo_compra_liq}  \n"
        f"🟥 **Venda:** {st.session_state.ultimo_venda_liq}"
    )
    
    if not tem_nomes:
        st.caption("Painel lido sem coluna de corretoras — certifique-se de que a captura do Book de Agentes está ativa.")

# ---- GATEKEEPER DE TRAVAS (MODO SOMBRA) ----
# MODO_SOMBRA=True: as travas AVALIAM e REGISTRAM, mas deixam o sinal passar.
# E o unico jeito de medir o que cada trava custaria: sinal bloqueado nao gera
# resultado, e sem resultado a base volta com 100% de acerto e zero poder de
# prova. Vire para False so depois de alguns dias de log.
MODO_SOMBRA_GATEKEEPER = False   # ATIVO: as travas agora bloqueiam de verdade

COLUNAS_LOG_BLOQUEIO = [
    "DataBloqueio", "MotivoBloqueio", "Modo", "Ativo", "PrecoEntrada", "Score",
    "Momentum", "RompimentoDispara", "ReversaoExtremo", "Regime",
    "VolumeFinanceiro", "VolumeCandle",
    "Acao", "PosRange", "DistanciaMM9", "AncoraEntrada",
    "SaldoAgressaoPct", "ViesFluxo", "FluxoLido", "DistanciaOfertante",
]


def _avaliar_travas(gatilho):
    """Devolve o motivo do bloqueio ou None. Nao decide nada sozinho."""
    g = gatilho or {}

    # 1. Exaustao de Score. Base de 165 operacoes: 7 casos, 14,3% de acerto,
    #    -14,7 pts. Evento raro, mas negativo em toda amostragem.
    if num(g.get("Score", 0)) >= 7:
        # Score 7 COM setup ancorado (reversao, pullback ou absorcao) nao e
        # exaustao: e confluencia maxima. So veta quando vem sozinho.
        _anc = (str(g.get("ReversaoExtremo", "")).lower() == "sim"
                or str(g.get("PullbackFavoravel", "")).lower() == "sim"
                or str(g.get("AbsorcaoFavoravel", "")).lower() == "sim")
        if not _anc:
            return "Score de exaustao (>= 7) sem ancora de setup"

    # 2. Momentum: FILTRO DE ENTRADA, nao de direcao.
    #    A trava antiga desligava o sinal na direcao DO movimento — era ela que
    #    vetava as compras corretas no meio da perna de alta. Agora bloqueia
    #    apenas (a) operacao CONTRA o momentum confirmado ou (b) entrada
    #    estirada da MM9 sem ancora de pullback/absorcao.
    _mom = str(g.get("Momentum", "")).strip()
    _acao_g = str(g.get("Acao", "")).strip().lower()
    _dist9 = num(g.get("DistanciaMM9", 0))
    _ancora = str(g.get("AncoraEntrada", "")).strip().lower() == "sim"

    if _mom in ("alta_forte", "alta") and _acao_g == "venda":
        return "Venda contra momentum de alta"
    if _mom in ("baixa_forte", "baixa") and _acao_g == "compra":
        return "Compra contra momentum de baixa"
    if (_mom in ("alta_forte", "baixa_forte") and _acao_g in ("compra", "venda")
            and _dist9 >= LIMITE_DIST_MM9_ENTRADA and not _ancora):
        return "Entrada estirada da MM9 (%.1f pts) — aguardar reaproximacao" % _dist9

    # 3. Rompimento sem suporte. Campo AUSENTE nao e campo negativo: nos dias
    #    antigos ReversaoExtremo nem existia, e tratar vazio como "nao" fazia a
    #    trava parecer eficaz quando so estava marcando dias antigos.
    # 2b. Fluxo neutro nao arma. Espelha o filtro da classificacao para que um
    #     sinal ARMADO por outro caminho tambem seja barrado.
    if _acao_g in ("compra", "venda") and EXIGE_FLUXO_DIRECIONAL and str(g.get("FluxoLido", "")) == "sim":
        _agr_g = num(g.get("SaldoAgressaoPct", 50.0))
        _vf_g = str(g.get("ViesFluxo", "indefinido")).strip().lower()
        if _acao_g == "compra":
            if not (_agr_g >= SALDO_AGRESSAO_MINIMO or _vf_g == "comprador"):
                return "Fluxo sem direcao compradora (agressao %.0f%%)" % _agr_g
        else:
            if not (_agr_g <= (100.0 - SALDO_AGRESSAO_MINIMO) or _vf_g == "vendedor"):
                return "Fluxo sem direcao vendedora (agressao %.0f%%)" % _agr_g

    if str(g.get("RompimentoDispara", "")).strip() == "sim":
        reversao = g.get("ReversaoExtremo", None)
        regime = str(g.get("Regime", "indefinido")).strip()
        if reversao is None or str(reversao).strip() == "":
            return None  # sem dado para julgar -> trava nao aplicavel
        # So e falso rompimento quando a entrada PERSEGUE a ponta do range.
        # Vender no terco superior ou comprar no terco inferior nao e perseguir:
        # a trava antiga vetava vendas que estavam na direcao certa.
        _pr = num(g.get("PosRange", -1))
        _persegue = ((_acao_g == "compra" and _pr >= 70.0) or
                     (_acao_g == "venda" and 0.0 <= _pr <= 30.0))
        if (str(reversao).strip() != "sim"
                and regime not in ("pullback_up", "pullback_down")
                and _persegue):
            return "Falso rompimento perseguindo a ponta do range"

    return None


def registrar_bloqueio(gatilho, motivo, nome_arquivo="log_armadilhas_evitadas.csv"):
    """Grava o sinal avaliado com colunas FIXAS.
    A versao anterior montava o cabecalho a partir das chaves do primeiro sinal:
    o segundo sinal com uma chave a mais levantava ValueError, e um com chave a
    menos gravava desalinhado."""
    g = gatilho or {}
    linha = {
        "DataBloqueio": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "MotivoBloqueio": motivo,
        "Modo": "sombra" if MODO_SOMBRA_GATEKEEPER else "ativo",
        "Ativo": g.get("Ativo", ""),
        "PrecoEntrada": g.get("PrecoEntrada", 0),
        "Score": g.get("Score", 0),
        "Momentum": g.get("Momentum", ""),
        "RompimentoDispara": g.get("RompimentoDispara", ""),
        "ReversaoExtremo": g.get("ReversaoExtremo", ""),
        "Regime": g.get("Regime", ""),
        "VolumeFinanceiro": g.get("VolumeFinanceiro", 0),
        "VolumeCandle": g.get("VolumeCandle", 0),
        "Acao": g.get("Acao", ""),
        "PosRange": g.get("PosRange", -1),
        "DistanciaMM9": g.get("DistanciaMM9", 0),
        "AncoraEntrada": g.get("AncoraEntrada", ""),
        "SaldoAgressaoPct": g.get("SaldoAgressaoPct", 50.0),
        "ViesFluxo": g.get("ViesFluxo", ""),
        "FluxoLido": g.get("FluxoLido", ""),
        "DistanciaOfertante": g.get("DistanciaOfertante", 0),
    }
    existe = os.path.isfile(nome_arquivo)
    try:
        with open(nome_arquivo, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS_LOG_BLOQUEIO, extrasaction="ignore")
            if not existe:
                w.writeheader()
            w.writerow(linha)
    except Exception:
        pass


def validar_sinal_entrada(gatilho):
    """(permitido, status). Em modo sombra sempre permite, mas grava o motivo."""
    motivo = _avaliar_travas(gatilho)
    if not motivo:
        if isinstance(gatilho, dict):
            gatilho["MotivoBloqueioSimulado"] = ""
        return True, "SINAL VALIDADO"

    if isinstance(gatilho, dict):
        gatilho["MotivoBloqueioSimulado"] = motivo
    registrar_bloqueio(gatilho, motivo)

    if MODO_SOMBRA_GATEKEEPER:
        return True, "SOMBRA: passaria bloqueado (" + motivo + ")"
    return False, "BLOQUEIO: " + motivo


def colunas_gatekeeper(contexto, dados_tela, preco):
    """Avalia as travas e devolve as colunas do gatekeeper para o CSV."""
    ctx = contexto or {}
    tem_reversao = "reversao_extremo" in ctx
    _preco_g = num(preco) or num((dados_tela or {}).get("preco_atual", 0))
    _mm9_g = num((dados_tela or {}).get("mm9", 0))
    _dist9_g = round(abs(_preco_g - _mm9_g), 2) if (_preco_g > 0 and _mm9_g > 0) else 0.0
    _acao_ctx = str(ctx.get("acao_final") or ctx.get("acao_pretendida")
                    or ctx.get("acao_objetiva") or "").strip().lower()
    _ancora_ctx = "sim" if (ctx.get("pullback_favoravel") or ctx.get("reversao_extremo")
                            or ctx.get("absorcao_favoravel")) else "nao"
    g = {
        "Ativo": ativo_canonico((dados_tela or {}).get("ativo", "")),
        "Acao": _acao_ctx,
        "PosRange": num(ctx.get("pos_range", -1)),
        "DistanciaMM9": _dist9_g,
        "AncoraEntrada": _ancora_ctx,
        "SaldoAgressaoPct": num(ctx.get("saldo_agressao_pct",
                                        ctx.get("agressao_pct_leitura", 50.0))),
        "ViesFluxo": str(ctx.get("vies_fluxo_lido",
                                 (dados_tela or {}).get("vies_fluxo", "indefinido"))),
        "FluxoLido": "sim" if ctx.get("book_valido", False) else "nao",
        "DistanciaOfertante": num(ctx.get("distancia_maior_ofertante", 0)),
        "PrecoEntrada": preco,
        "Score": ctx.get("score", 0),
        "Momentum": ctx.get("momentum", ""),
        "RompimentoDispara": "sim" if ctx.get("rompimento_dispara") else "nao",
        "ReversaoExtremo": ("sim" if ctx.get("reversao_extremo") else "nao") if tem_reversao else "",
        "Regime": ctx.get("regime", ""),
        "VolumeFinanceiro": ctx.get("volume_financeiro", 0),
        "VolumeCandle": ctx.get("volume_atual", 0),
    }
    permitido, status = validar_sinal_entrada(g)
    return {
        "MotivoBloqueioSimulado": g.get("MotivoBloqueioSimulado", ""),
        "GatekeeperModo": "sombra" if MODO_SOMBRA_GATEKEEPER else "ativo",
        "GatekeeperStatus": status,
        "GatekeeperPermitido": "sim" if permitido else "nao",
    }


# ---- GUARDA DE VOLUME: envelopa classificar_contexto ----
_classificar_contexto_original = classificar_contexto


def aplicar_guarda_volume(ctx_res, dados_tela):
    """Classifica o volume do candle. Nao bloqueia: na amostra de 119 operacoes
    fechadas o volume 0 rendeu 73,3% de acerto, ou seja, e falha de leitura da
    tela e nao sinal de mercado. O peso real fica com o motor de conviccao."""
    try:
        vol = num((dados_tela or {}).get("volume", 0))
    except Exception:
        vol = 0.0
    ctx_res["volume_candle_lido"] = vol
    if vol <= 0:
        ctx_res["volume_status"] = "nao_lido"
        ctx_res["volume_aviso"] = "Volume do candle não lido — confirme na tela antes de dobrar o lote."
    elif vol < VOLUME_MINIMO_SAUDAVEL:
        ctx_res["volume_status"] = "fraco"
        ctx_res["volume_aviso"] = f"Volume de {int(vol)} contratos abaixo do mínimo saudável."
    elif vol < VOLUME_IDEAL:
        ctx_res["volume_status"] = "medio"
        ctx_res["volume_aviso"] = ""
    else:
        ctx_res["volume_status"] = "saudavel"
        ctx_res["volume_aviso"] = ""
    return ctx_res


def _chave_leitura(dados_tela, ignorar_macro):
    d = dados_tela or {}
    return "|".join([
        str(d.get("ativo", "")),
        str(d.get("hora_replay", "") or d.get("hora", "")),
        "%.2f" % num(d.get("preco_atual", 0)),
        "%.2f" % num(d.get("mm9", 0)),
        "%.0f" % num(d.get("volume", 0)),
        "1" if ignorar_macro else "0",
    ])


def classificar_contexto(dados_tela, fechamento_ant=None, ignorar_macro=False):
    # FONTE UNICA DE VERDADE: painel, fala e CSV chamavam esta funcao
    # separadamente e podiam mostrar decisoes diferentes para o MESMO instante
    # (painel EXECUTAR VENDA 81% x log compra 15%). A primeira classificacao da
    # leitura fica em cache e todos os consumidores leem a mesma.
    _chave = _chave_leitura(dados_tela, ignorar_macro)
    _cache = st.session_state.get("cache_contexto") or {}
    if _cache.get("chave") == _chave and isinstance(_cache.get("ctx"), dict):
        return _cache["ctx"]
    ctx_res = _classificar_contexto_original(dados_tela, fechamento_ant, ignorar_macro)
    try:
        ctx_res = aplicar_guarda_volume(ctx_res, dados_tela)
        ctx_res = aplicar_guarda_volume_financeiro(ctx_res, dados_tela)
    except Exception:
        pass
    try:
        ctx_res = avaliar_conviccao(ctx_res, dados_tela)
    except Exception:
        pass
    if isinstance(ctx_res, dict):
        ctx_res["chave_leitura"] = _chave
        st.session_state["cache_contexto"] = {"chave": _chave, "ctx": ctx_res}
    return ctx_res



# =============================================================================
# CORRECOES POS-REPLAY 14/08 — envelopam as funcoes ja definidas acima.
# Ficam aqui, depois de todas as definicoes e antes da interface, para haver um
# unico lugar a revisar quando o proximo replay apontar desvio.
# =============================================================================

# ---- A/C/D) Serie de leituras: fora de ciclo nao entra, ativo canonico, disco --
def _hist_disco_ler(ativo):
    """Le a serie salva em disco. Reinicio do app deixava o historico com duas
    leituras e delta_3 sem janela."""
    try:
        with open(ARQ_HIST_LEITURAS, "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        h = d.get(str(ativo or ""), [])
        return h[:8] if isinstance(h, list) else []
    except Exception:
        return []


def _hist_disco_salvar(ativo, h):
    try:
        try:
            with open(ARQ_HIST_LEITURAS, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
        except Exception:
            d = {}
        d[str(ativo or "")] = (h or [])[:8]
        with open(ARQ_HIST_LEITURAS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


_registrar_leitura_historico_v1 = registrar_leitura_historico
_calcular_momentum_v1 = calcular_momentum


def registrar_leitura_historico(dados_tela):
    """Mesma serie de antes, com tres travas:
    1. o ativo e normalizado ANTES de indexar (WDOU26 / WDO26 / WDO eram tres
       series diferentes na mesma sessao);
    2. leitura fora do ciclo de 300 s nao entra na serie;
    3. a serie e hidratada do disco quando a sessao reinicia."""
    d = dados_tela if isinstance(dados_tela, dict) else {}
    _at = ativo_canonico(d.get("ativo", ""))
    if _at:
        d["ativo"] = _at

    _serie_ativo = str(st.session_state.get("hist_leituras_ativo", "") or "")
    if _at and _serie_ativo and _serie_ativo != _at:
        # Troca real de contrato: serie antiga nao descreve este ativo.
        st.session_state["hist_leituras"] = _hist_disco_ler(_at)
        st.session_state["hist_momentum"] = []
    if not st.session_state.get("hist_leituras"):
        st.session_state["hist_leituras"] = _hist_disco_ler(_at)
    if _at:
        st.session_state["hist_leituras_ativo"] = _at

    if st.session_state.get("leitura_fora_de_ciclo"):
        return list(st.session_state.get("hist_leituras", []))[:8]

    h = _registrar_leitura_historico_v1(d)
    _hist_disco_salvar(_at, h)
    return h


def calcular_momentum(dados_tela):
    """Fora de ciclo devolve o ultimo momentum calculado sem tocar em
    hist_momentum: a leitura extra deixa de inverter direcao e regime."""
    if st.session_state.get("leitura_fora_de_ciclo"):
        _prev = st.session_state.get("ultimo_momentum")
        if isinstance(_prev, dict) and _prev:
            out = dict(_prev)
            out["fora_de_ciclo"] = True
            return out
    out = _calcular_momentum_v1(dados_tela)
    if isinstance(out, dict):
        out["fora_de_ciclo"] = False
        # 'forte' exige janela de 3 leituras fechada.
        if not out.get("delta_3_valido", True):
            if out.get("momentum") == "alta_forte":
                out["momentum"] = "alta"
            elif out.get("momentum") == "baixa_forte":
                out["momentum"] = "baixa"
            st.session_state["ultimo_momentum"] = out
    return out


# ---- I) Abertura fora do intervalo minima-maxima ----
_validar_leitura_v2 = validar_leitura


def validar_leitura(dt):
    """Abertura de 5214 com maxima 5204,5 e minima 5201 era numero perdido na
    leitura da tela. Descarta em vez de propagar para o calculo de gap."""
    if isinstance(dt, dict):
        _mx, _mn = num(dt.get("maxima", 0)), num(dt.get("minima", 0))
        _ab = num(dt.get("abertura", 0))
        if _mx > _mn > 0 and _ab > 0 and not (_mn - 0.5 <= _ab <= _mx + 0.5):
            dt["abertura_lida_invalida"] = _ab
            dt["abertura"] = 0.0
    return _validar_leitura_v2(dt)


# ---- H) Volume financeiro caindo no campo de contratos ----
_aplicar_guarda_volume_v1 = aplicar_guarda_volume


def aplicar_guarda_volume(ctx_res, dados_tela):
    d = dict(dados_tela or {})
    _v = num(d.get("volume", 0))
    if _v > LIMITE_CONTRATOS_PLAUSIVEL:
        # 427.450 "contratos" em um candle de 5 min do WDO e volume FINANCEIRO:
        # aceito como contratos, invalidava o piso de volume da leitura.
        d["volume"] = 0
        ctx_res = _aplicar_guarda_volume_v1(ctx_res, d)
        ctx_res["volume_atual"] = 0
        ctx_res["volume_candle_lido"] = 0
        ctx_res["volume_status"] = "nao_lido"
        ctx_res["volume_financeiro_no_campo_errado"] = _v
        ctx_res["volume_aviso"] = (
            "Campo de volume trouxe %.0f — valor financeiro, nao contratos. "
            "Leitura de volume descartada nesta analise." % _v)
        return ctx_res
    return _aplicar_guarda_volume_v1(ctx_res, d)


# ---- F) Conviccao: escala unica e piso de direcao ----
_consolidar_veredito_v1 = consolidar_veredito


def processar_conviction(v, contexto=None, contexto_fluxo=None):
    if not isinstance(v, dict):
        v = {}
    if not isinstance(contexto_fluxo, dict):
        contexto_fluxo = {}
    _agr_pct = num(contexto_fluxo.get("agressao_pct", 50.0))
    v["agressao_pct_veredito"] = _agr_pct

    ctx = contexto or {}
    _cv = int(num(v.get("convicao", 0)))
    _un = _cv
    if "conviccao_ponderada" in ctx:
        # Painel mostrava 88% e o log 0% para a MESMA leitura. Passam a ser a
        # mesma escala, na leitura conservadora: a menor das duas.
        _cp = int(num(ctx.get("conviccao_ponderada", 0)))
        _un = min(_cv, _cp)
        v["convicao_ponderada"] = _cp
    v["convicao_veredito"] = _cv
    v["convicao"] = _un
    if _un < PISO_CONVICCAO_DIRECAO:
        # Antes apontava compra com 5% de conviccao contra o proprio vies.
        v["direcao"] = "indefinida"
        v["acao_sugerida"] = "aguardar"
        v["resumo"] = ("Convicção de %d%% abaixo do piso de %d%% — "
                       "sem direção definida." % (_un, PISO_CONVICCAO_DIRECAO))
    return v


def consolidar_veredito(contexto, mudanca_desc="", mudanca_ativa=False, contexto_fluxo=None):
    v = _consolidar_veredito_v1(contexto, mudanca_desc, mudanca_ativa)
    try:
        conv = float(v.get("conviccao", 0) or 0)
        conv_pond = float(v.get("conviccao_ponderada", conv) or conv)
        conv_unificada = round(min(conv, conv_pond), 1)
        v["conviccao_unificada"] = conv_unificada
        if conv_unificada < PISO_CONVICCAO_DIRECAO:
            v["direcao"] = "neutro"
            if str(v.get("acao", "")).lower() in ("compra", "venda"):
                v["acao"] = "espera"
    except Exception:
        pass
    return processar_conviction(v, contexto=contexto, contexto_fluxo=contexto_fluxo)


# ---- G) Gatekeeper: filtro de ENTRADA, nao de direcao ----
_avaliar_travas_v1 = _avaliar_travas


def _avaliar_travas(gatilho):
    motivo = _avaliar_travas_v1(gatilho)
    if not motivo:
        return None
    g = gatilho or {}
    if "momentum" not in str(motivo).lower():
        return motivo
    _acao = str(g.get("Acao", "")).strip().lower()
    _mom = str(g.get("Momentum", "")).strip().lower()
    _pr = num(g.get("PosRange", -1))
    _d9 = num(g.get("DistanciaMM9", 0))
    _a_favor = ((_acao == "compra" and _mom.startswith("alta")) or
                (_acao == "venda" and _mom.startswith("baixa")))
    _estirada = _d9 > LIMITE_DIST_MM9_ENTRADA
    _ponta = ((_acao == "compra" and _pr >= PONTA_RANGE_COMPRA) or
              (_acao == "venda" and 0.0 <= _pr <= PONTA_RANGE_VENDA))
    if _ponta:
        # O bloqueio existe, mas o motivo e a ponta do range — nao o momentum.
        return ("Entrada de %s na ponta do range (%.0f%% do dia)" % (_acao, _pr))
    if _a_favor and not _estirada:
        # Compra a favor da alta, a 4,5 pts da MM9 e no meio do range nao e
        # entrada estirada nem contra o movimento: momentum nao bloqueia.
        return None
    return motivo


# ---- E) Em ESPERA a geometria e referencia do vies ----
def _direcao_referencia(ctx):
    """Direcao que a leitura esta descrevendo, mesmo sem gatilho."""
    c = ctx or {}
    for _k in ("acao_pretendida", "acao_objetiva", "veredito_direcao"):
        _v = str(c.get(_k, "")).strip().lower()
        if _v in ("compra", "venda"):
            return _v
    _t = (str(c.get("vies_objetivo", "")) + " " + str(c.get("vies", "")) + " " +
          str(c.get("regime", "")) + " " + str(c.get("momentum", ""))).lower()
    _alta = any(p in _t for p in ("alta", "compra", "trend_up", "pullback_up"))
    _baixa = any(p in _t for p in ("baixa", "queda", "venda", "trend_down", "pullback_down"))
    if _alta and not _baixa:
        return "compra"
    if _baixa and not _alta:
        return "venda"
    return ""


_calcular_alvo_dinamico_v1 = calcular_alvo_dinamico


def calcular_alvo_dinamico(preco, acao, estrategia, dados_tela=None,
                           agentes_info=None, fechamento_ant=None):
    _a = str(acao or "").strip().lower()
    if _a in ("compra", "venda"):
        return _calcular_alvo_dinamico_v1(preco, acao, estrategia, dados_tela,
                                          agentes_info, fechamento_ant)
    # ESPERA: alvo acima do preco com vies de baixa era defeito de registro.
    _ref = str(st.session_state.get("direcao_referencia_atual") or "")
    if _ref in ("compra", "venda"):
        n = _calcular_alvo_dinamico_v1(preco, _ref, estrategia, dados_tela,
                                       agentes_info, fechamento_ant)
        if isinstance(n, dict):
            n = dict(n)
            n["base_alvo"] = "referencia_" + _ref
            n["base_stop"] = "referencia_" + _ref
            n["referencia_direcao"] = _ref
            n["em_espera"] = True
        return n
    n = _calcular_alvo_dinamico_v1(preco, "compra", estrategia, dados_tela,
                                   agentes_info, fechamento_ant)
    if isinstance(n, dict):
        n = dict(n)
        n.update({"alvo": 0.0, "stop": 0.0, "base_alvo": "sem_direcao",
                  "base_stop": "sem_direcao", "geometria_valida": False,
                  "em_espera": True})
    return n


# ---- Fonte unica: a direcao de referencia sai da MESMA classificacao ----
_classificar_contexto_v2 = classificar_contexto


def classificar_contexto(dados_tela, fechamento_ant=None, ignorar_macro=False):
    ctx_res = _classificar_contexto_v2(dados_tela, fechamento_ant, ignorar_macro)
    if isinstance(ctx_res, dict):
        _ref = _direcao_referencia(ctx_res)
        ctx_res["direcao_referencia"] = _ref
        ctx_res["leitura_fora_de_ciclo"] = ("sim" if st.session_state.get(
            "leitura_fora_de_ciclo") else "nao")
        try:
            st.session_state["direcao_referencia_atual"] = _ref
        except Exception:
            pass
    return ctx_res


# ---- PAINEL DE COMANDO (topo da pagina) ----
def _render_indices(lista, lado):
    """Barras dos indicadores que estao pesando nesta leitura."""
    if not lista:
        return ('<div style="font-size:12px;color:#8892a4;font-style:italic;">'
                'nenhum nesta leitura</div>')
    cor = "#00e676" if lado == "favor" else "#ff5252"
    linhas = []
    for i in lista[:4]:
        larg = int(max(6, min(100, abs(i["peso"]) * 2.5)))
        linhas.append(
            f'<div style="display:grid;grid-template-columns:1fr 52px 46px;gap:6px;'
            f'align-items:center;font-size:12px;padding:3px 0;">'
            f'<div>{i["rotulo"]}'
            f'<div style="background:#0e1117;border-radius:3px;height:5px;margin-top:3px;">'
            f'<div style="background:{cor};height:5px;width:{larg}%;border-radius:3px;"></div></div></div>'
            f'<div style="color:{cor};font-weight:700;text-align:right">{i["acerto"]:.0f}%</div>'
            f'<div style="color:#8892a4;text-align:right">{i["peso"]:+d}</div></div>')
    return "".join(linhas)


def render_painel_comando(ctx_res, dados_tela, pe):
    """SUGESTAO UNIFICADA — primeira e principal informacao da pagina.
    A conviccao vem da soma ponderada dos indicadores pelo acerto historico
    de cada um; os melhores empurram para cima, os piores para baixo."""
    conv = int(num(ctx_res.get("conviccao_ponderada", 0)))
    acao = str(ctx_res.get("sugestao_acao", "FORA"))
    cor = str(ctx_res.get("sugestao_cor", "#8892a4"))
    texto = str(ctx_res.get("sugestao_texto", ""))
    preco = num((dados_tela or {}).get("preco_atual", 0))
    hora = (dados_tela or {}).get("hora_replay", "") or datetime.now().strftime("%H:%M")

    _exec_ok = str(ctx_res.get("execucao_liberada", "nao")).lower() == "sim"
    if conv >= 70 and _exec_ok:
        classe = "compra" if "COMPRA" in acao else ("venda" if "VENDA" in acao else "neutro")
    elif conv >= 45:
        classe = "espera"
    else:
        classe = "venda" if "NÃO" in acao else "neutro"

    alvo = stop = 0.0
    _geom_ok = False
    try:
        _dir = ("compra" if "COMPRA" in acao else "venda" if "VENDA" in acao else
                str(ctx_res.get("acao_pretendida") or ctx_res.get("acao_objetiva")
                    or ctx_res.get("vies") or "").strip().lower())
        if _dir not in ("compra", "venda"):
            raise ValueError("sem direcao definida")
        _n = calcular_alvo_dinamico(
            preco, _dir,
            ctx_res.get("estrategia", st.session_state.estrategia_operacional),
            dados_tela=dados_tela,
            agentes_info=st.session_state.get("ultimos_agentes", {}),
            fechamento_ant=ler_fechamento_anterior())
        alvo, stop = round(num(_n.get("alvo", 0)), 2), round(num(_n.get("stop", 0)), 2)
        _geom_ok = bool(alvo) and bool(stop) and _n.get("geometria_valida", True) is not False
    except Exception:
        _geom_ok = False

    # Em ESPERA a geometria e apenas REFERENCIA. Exibir alvo de compra para uma
    # leitura com vies de venda (alvo acima do preco) era defeito de registro.
    _armado = (("EXECUTAR" in acao) or ("MEIA POSIÇÃO" in acao)) and _exec_ok
    if not _geom_ok:
        _alvo_txt, _stop_txt = "—", "—"
    elif _armado:
        _alvo_txt, _stop_txt = f"{alvo:.2f}", f"{stop:.2f}"
    else:
        _alvo_txt, _stop_txt = f"{alvo:.2f} (ref.)", f"{stop:.2f} (ref.)"

    favor = ctx_res.get("indices_favor", []) or []
    contra = ctx_res.get("indices_contra", []) or []
    aviso_vol = str(ctx_res.get("volume_aviso", ""))
    ajustes = ctx_res.get("ajustes_otimizacao", []) or []

    st.markdown(f"""
<div class="hero {classe}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap;">
    <div style="flex:1;min-width:260px;">
      <div class="acao" style="color:{cor}">{acao}</div>
      <div class="sub">{hora} · preço <b>{preco:.2f}</b> · 🎯 alvo <b>{_alvo_txt}</b>
           · 🛑 stop <b>{_stop_txt}</b> · score <b>{ctx_res.get("score", 0)}/{ctx_res.get("score_minimo_usado", 0)}</b></div>
      <div class="linha" style="color:#dfe5f0">{texto}</div>
    </div>
    <div style="min-width:170px;text-align:right;">
      <div style="font-size:11px;color:#8892a4;text-transform:uppercase;letter-spacing:1px;">Convicção ponderada</div>
      <div style="font-size:42px;font-weight:800;color:{cor};line-height:1;">{conv}%</div>
      <div style="background:#0e1117;border-radius:5px;height:9px;margin-top:6px;overflow:hidden;">
        <div style="background:{cor};height:9px;width:{conv}%;"></div></div>
      <div style="font-size:10px;color:#8892a4;margin-top:4px;">
        executar ≥ 70% · meia posição ≥ 45%</div>
    </div>
  </div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
  <div class="book-wrap">
    <div class="book-tit"><span>✅ A FAVOR — MAIOR ACERTO HISTÓRICO</span>
      <span class="pill ok">{sum(i["peso"] for i in favor):+d}</span></div>
    {_render_indices(favor, "favor")}
  </div>
  <div class="book-wrap">
    <div class="book-tit"><span>⚠️ CONTRA — ARMADILHAS MEDIDAS</span>
      <span class="pill bad">{sum(i["peso"] for i in contra):+d}</span></div>
    {_render_indices(contra, "contra")}
  </div>
</div>
""", unsafe_allow_html=True)

    if ajustes or aviso_vol:
        itens = "".join(f'<div style="font-size:12px;color:#40c4ff;padding:2px 0;">🔧 {a}</div>'
                        for a in ajustes)
        if aviso_vol:
            itens += (f'<div style="font-size:12px;color:#ffd740;padding:2px 0;">'
                      f'⚠️ {aviso_vol}</div>')
        st.markdown(f'<div style="background:#161b2b;border-left:3px solid #40c4ff;'
                    f'border-radius:8px;padding:8px 13px;margin-bottom:10px;">{itens}</div>',
                    unsafe_allow_html=True)



# =========================
# HEADER
# =========================
sg_atual = st.session_state.ultimo_status_gatilho
badge_map = {
    "ARMADO": ("badge-armado","🟢 ARMADO"),
    "BLOQUEADO": ("badge-bloqueado","🔴 BLOQUEADO"),
    "ESPERA": ("badge-espera","🟡 ESPERA"),
    "AGUARDANDO": ("badge-aguardando","⚪ AGUARDANDO"),
}
badge_cls, badge_txt = badge_map.get(sg_atual, ("badge-aguardando","⚪"))

col_h1, col_h2, col_h3 = st.columns([3,1,1])
with col_h1:
    st.markdown("# 🤖 AutoPro — Radar Institucional")
    st.markdown(f'<span class="status-badge {badge_cls}">{badge_txt}</span>', unsafe_allow_html=True)
with col_h2:
    mac_h = ler_dados_macro()
    st.markdown(f'<div class="metric-card"><div class="label">DXY</div><div class="value blue">{mac_h.get("DXY","N/A")}</div></div>', unsafe_allow_html=True)
with col_h3:
    st.markdown(f'<div class="metric-card"><div class="label">PTAX Bacen</div><div class="value gold">{mac_h.get("PTAX","N/A")}</div></div>', unsafe_allow_html=True)


# =============================================================================
# CICLO GLOBAL DE ANALISE — vale para TODAS as abas
# Roda antes de montar as abas: o ciclo de 5 min e o disparo pos-anuncio
# passam a funcionar em qualquer aba selecionada, nao so na primeira.
# =============================================================================
_jan_glob = estado_janela_operacional()
st.session_state["estado_janela"] = _jan_glob
_na_janela_glob = bool(_jan_glob.get("dentro"))
_int_glob = intervalo_analise_atual()
st.session_state["intervalo_ciclo_atual"] = _int_glob
_dec_glob = time.time() - num(st.session_state.get("ultimo_ciclo_analise", 0))
st.session_state["segundos_proxima_analise"] = max(0, int(_int_glob - _dec_glob))

# Troca de configuracao de pregao (data do replay, modo replay, ativo) libera
# o recalculo das faixas — fora disso elas ficam congeladas.
_cfg_pregao = "|".join([
    str(st.session_state.get("modo_replay", False)),
    str(st.session_state.get("replay_data", "")),
    str((st.session_state.get("ultimos_dados_tela") or {}).get("ativo", "")),
])
if st.session_state.get("_cfg_pregao_anterior") != _cfg_pregao:
    invalidar_faixas_travadas()
    # Trocar a data do replay descarta a leitura de tela do pregao anterior:
    # ela pertencia a outra configuracao de pregao.
    st.session_state.pop("ref_pregao_anterior_tela", None)
    st.session_state["_cfg_pregao_anterior"] = _cfg_pregao

_disp_glob, _chave_glob, _evento_glob = (False, "", "")
if st.session_state.get("analise_automatica") and _na_janela_glob:
    try:
        _disp_glob, _chave_glob, _evento_glob = disparo_pos_anuncio()
    except Exception:
        _disp_glob, _chave_glob, _evento_glob = (False, "", "")

_lig_glob = (st.session_state.get("analise_automatica") and not _na_janela_glob
             and precisa_leitura_de_ligacao())

if st.session_state.get("analise_automatica") and CHAVE_OPENROUTER and (
        (_na_janela_glob and (_dec_glob >= _int_glob or _disp_glob)) or _lig_glob):
    st.session_state["origem_ciclo_atual"] = (
        "ligacao" if _lig_glob else
        "anuncio" if (_disp_glob and _dec_glob < _int_glob) else "ciclo_5min")
    if _disp_glob:
        try:
            atualizar_macro_agendado(forcar=True)
        except Exception:
            pass
        st.session_state["ultimo_disparo_anuncio"] = (
            f"{datetime.now().strftime('%H:%M:%S')} — {_evento_glob}")
    st.session_state["leitura_fora_de_ciclo"] = bool(_lig_glob)
    with st.spinner("Analisando o pregão..."):
        try:
            executar_analise()
            st.session_state.ultimo_ciclo_analise = time.time()
            if _disp_glob and _chave_glob:
                registrar_disparo_anuncio(_chave_glob)
            if _lig_glob:
                registrar_leitura_de_ligacao()
        except Exception as _e_glob:
            st.session_state["ultimo_erro_ciclo"] = str(_e_glob)


# =========================
# ABAS PRINCIPAIS
# =========================
aba1, aba2, aba3, aba4 = st.tabs([
    "🤖 Radar Institucional", "📈 Sinal Mini Dólar 9h",
    "📅 Calendário + Notícias", "🎯 Decisão Rápida"])


# ============================================================
# ABA 1 — RADAR INSTITUCIONAL
# ============================================================
with aba1:


    # ------------------------------------------------------------------
    # 1. DECISAO — primeira coisa da pagina
    # ------------------------------------------------------------------
    _ig_topo = st.session_state.modo_replay and not st.session_state.usar_macro_no_replay
    _dt_topo = st.session_state.get("ultimos_dados_tela", {})
    _pe_topo = ESTRATEGIAS[st.session_state.estrategia_operacional]
    if _dt_topo:
        _ctx_topo = classificar_contexto(
            _dt_topo, ler_fechamento_anterior() if not _ig_topo else None, _ig_topo)
        render_painel_comando(_ctx_topo, _dt_topo, _pe_topo)
    else:
        st.markdown('<div class="hero neutro"><div class="acao" style="color:#8892a4">'
                    'AGUARDANDO LEITURA</div><div class="sub">Clique em Executar Análise '
                    'para gerar a primeira decisão.</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">⚡ Ação e profundidade do book</div>', unsafe_allow_html=True)
    # --- Botão de execução com RESUMO PREVISIONAL + AÇÃO DOS AGENTES ---
    st.markdown("")
    col_btn, col_resumo, col_agentes = st.columns([1, 2, 2])
    with col_btn:
        rodar = st.button("▶️ Executar Análise", width='stretch')
    with col_resumo:
        if st.session_state.ultimos_dados_tela:
            _ig = st.session_state.modo_replay and not st.session_state.usar_macro_no_replay
            _ctx = classificar_contexto(st.session_state.ultimos_dados_tela, ler_fechamento_anterior() if not _ig else None, _ig)
            _a = _ctx.get("acao_pretendida", _ctx["acao_objetiva"])
            _est = _ctx["estrategia"]
            _pr = num(st.session_state.ultimos_dados_tela.get("preco_atual", 0))
            _hr = st.session_state.ultimos_dados_tela.get("hora_replay","") or datetime.now().strftime("%H:%M")
            _pad = _ctx.get("padrao_candle","")
            _pe = ESTRATEGIAS[_est]
            _sc = _ctx["score"]; _scm = _ctx["score_minimo_usado"]; _lim = _ctx["limiar"]
            _falta_lst = _ctx.get("falta_para_gatilho", [])
            _armado = (not _falta_lst) and _a in ["compra","venda"]

            def _fmt_alvo_stop(_dir, _preco, _pe):
                _n = calcular_alvo_dinamico(
                    _preco, _dir, _est,
                    dados_tela=st.session_state.ultimos_dados_tela,
                    agentes_info=st.session_state.get("ultimos_agentes", {}),
                    fechamento_ant=ler_fechamento_anterior() if not _ig else None,
                )
                return round(_n["alvo"], 2), round(_n["stop"], 2)

            _base_alvo_txt = _ctx.get("base_alvo", "fixo")
            _base_stop_txt = _ctx.get("base_stop", "fixo")

            # Detalhe do raciocínio: fica recolhido para não competir com a decisão.
            with st.expander("🔍 Por que esta decisão — leitura completa", expanded=False):
                # ---- INDICAÇÃO UNIFICADA (topo) ----
                _vd = st.session_state.get("ultimo_veredito", {}) or {}
                if _vd.get("direcao") and _vd.get("direcao") != "indefinida":
                    _vdir = _vd["direcao"]
                    _vcor = "#00e676" if _vdir == "compra" else "#ff5252"
                    _vconv = int(_vd.get("convicao", 0))
                    _vacao = str(_vd.get("acao_sugerida", "aguardar")).upper()
                    if _vconv < 30:
                        _vcor = "#ffd740"
                    _vdet = "<br>".join([f"• {d}" for d in (_vd.get("detalhe") or [])])
                    _vcon = ""
                    if _vd.get("contras"):
                        _vcon = ('<br><span style="color:#ff9800">⚠️ Contra: '
                                 + ", ".join(_vd["contras"]) + "</span>")
                    st.markdown(f'''<div style="background:linear-gradient(135deg,#0a1628,#050b14);border:3px solid {_vcor};border-radius:12px;padding:14px 18px;font-size:13px;line-height:1.75;margin-bottom:10px;">
    🧭 <b style="color:{_vcor};font-size:17px">INDICAÇÃO UNIFICADA — {_vacao}</b><br>
    <b>{_vd.get("fontes",0)} de 5 leituras</b> apontam <b style="color:{_vcor}">{_vdir.upper()}</b> · convicção <b>{_vconv}%</b>
    <div style="background:#0e1117;border-radius:8px;height:9px;margin:7px 0;overflow:hidden;">
    <div style="background:{_vcor};height:9px;width:{_vconv}%;"></div></div>
    <span style="color:#8892a4;font-size:12px">{_vdet}</span>{_vcon}
    </div>''', unsafe_allow_html=True)

                # ---- JANELA DE ABERTURA ----
                _ab = _ctx.get("abertura_info", {}) or {}
                if _ab.get("resumo"):
                    _obs = _ab.get("em_observacao")
                    _cor_ab = "#ffd740" if _obs else "#40c4ff"
                    _icone = "🕐" if _obs else "✅"
                    _titulo = "OBSERVANDO A ABERTURA — SEM GATILHO" if _obs else "ABERTURA CONCLUÍDA"
                    _gp = num(_ab.get("gap_pts", 0))
                    _linha_gap = ""
                    if _ab.get("fech_anterior"):
                        _linha_gap = (f'<br>Fechamento anterior <b>{num(_ab.get("fech_anterior")):.2f}</b> → '
                                      f'abertura <b>{num(_ab.get("abertura")):.2f}</b> ({_gp:+.1f} pts)')
                    st.markdown(f'''<div style="background:linear-gradient(135deg,#1a1400,#0f0c00);border:2px solid {_cor_ab};border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.7;margin-bottom:8px;">
    {_icone} <b style="color:{_cor_ab};font-size:15px">{_titulo}</b><br>
    {_ab.get("resumo","")}{_linha_gap}{("<br>🏦 " + _ctx.get("lotes_institucionais", {}).get("resumo", "")) if _ctx.get("lotes_institucionais", {}).get("resumo") else ""}
    </div>''', unsafe_allow_html=True)

                # ---- ROBO PREDITIVO ----
                _prev = _ctx.get("previsao", {}) or {}
                _rmp = _ctx.get("rompimento_candle", {}) or {}
                if _prev:
                    _pa5 = int(_prev.get("prob_alta_5", 50)); _pa10 = int(_prev.get("prob_alta_10", 50))
                    _dirp = _prev.get("direcao_prevista", "indefinido")
                    _corp = "#00e676" if _dirp == "compra" else ("#ff5252" if _dirp == "venda" else "#ffd740")
                    _txtp = "ALTA" if _dirp == "compra" else ("BAIXA" if _dirp == "venda" else "INDEFINIDA")
                    _fat = "<br>".join([f"• {f}" for f in (_prev.get("fatores") or [])[:4]]) or "• Sem fatores dominantes"
                    _rmp_html = ""
                    if _rmp.get("dispara"):
                        _rmp_html = f'<br>⚡ <b style="color:#ffd740">ROMPIMENTO CONFIRMADO</b> — {_rmp.get("motivo","")}'
                    elif _rmp.get("direcao") in ("venda_pendente", "compra_pendente"):
                        _rmp_html = f'<br>🎯 {_rmp.get("motivo","")}'
                    _velocidade_aviso = "" if _prev.get("velocidade_valida") else ' <span style="color:#ffd740">(sem histórico)</span>'
                    st.markdown(f'''<div style="background:linear-gradient(135deg,#0d1b2a,#0a1420);border:2px solid {_corp};border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.7;margin-bottom:8px;">
    🤖 <b style="color:{_corp};font-size:15px">PREVISÃO — TENDÊNCIA DE {_txtp}</b> · confiança <b>{_prev.get("confianca",0)}%</b><br>
    Em <b>5 min</b>: alta <b style="color:#00e676">{_pa5}%</b> · baixa <b style="color:#ff5252">{100-_pa5}%</b> · projeção <b>{num(_prev.get("projecao_5",0)):.2f}</b><br>
    Em <b>10 min</b>: alta <b style="color:#00e676">{_pa10}%</b> · baixa <b style="color:#ff5252">{100-_pa10}%</b> · projeção <b>{num(_prev.get("projecao_10",0)):.2f}</b><br>
    Velocidade <b>{num(_prev.get("velocidade_pts_min",0)):+.2f} pts/min</b>{_velocidade_aviso} · espaço livre acima <b>{num(_prev.get("espaco_alta",0)):.1f}</b> / abaixo <b>{num(_prev.get("espaco_baixa",0)):.1f}</b> pts{_rmp_html}<br>
    <span style="color:#8892a4">{_fat}</span>
    </div>''', unsafe_allow_html=True)

            if _armado and _a == "compra" and _pr > 0:
                _al, _stp = _fmt_alvo_stop("compra", _pr, _pe)
                _extra = f" · Padrão: <b>{_pad}</b>" if _pad and _pad != "nenhum" else ""
                _extra += f'<br>🎯 Alvo em <b>{_base_alvo_txt}</b> · 🛑 Stop em <b>{_base_stop_txt}</b>'
                if _ctx.get("gestao_posicao"):
                    _extra += f'<br>📐 <b>{_ctx["gestao_posicao"]}</b>'
                _est_esp = _ctx.get("estrategia_especial_nome","Nenhuma")
                if _est_esp and _est_esp != "Nenhuma":
                    _extra += f' · ⭐ <b style="color:#ffd740">{_est_esp}</b>'
                st.markdown(f'''<div style="background:linear-gradient(135deg,#003300,#001a00);border:2px solid #00e676;border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.7;">
🟢 <b style="color:#00e676;font-size:15px">GATILHO ARMADO — COMPRAR</b> às <b>{_hr}</b><br>
Preço: <b>{_pr:.2f}</b> · Alvo: <b style="color:#00e676">{_al:.2f}</b> (+{_pe["amp_fibo"]*1.61:.1f} pts) · Stop: <b style="color:#ff5252">{_stp:.2f}</b> (-{_pe["stop_pts"]} pts) · Score <b>{_sc}/{_scm}</b> · Limiar <b>{_lim}%</b>{_extra}
</div>''', unsafe_allow_html=True)
            elif _armado and _a == "venda" and _pr > 0:
                _al, _stp = _fmt_alvo_stop("venda", _pr, _pe)
                _extra = f" · Padrão: <b>{_pad}</b>" if _pad and _pad != "nenhum" else ""
                _extra += f'<br>🎯 Alvo em <b>{_base_alvo_txt}</b> · 🛑 Stop em <b>{_base_stop_txt}</b>'
                if _ctx.get("gestao_posicao"):
                    _extra += f'<br>📐 <b>{_ctx["gestao_posicao"]}</b>'
                _est_esp = _ctx.get("estrategia_especial_nome","Nenhuma")
                if _est_esp and _est_esp != "Nenhuma":
                    _extra += f' · ⭐ <b style="color:#ffd740">{_est_esp}</b>'
                st.markdown(f'''<div style="background:linear-gradient(135deg,#330000,#1a0000);border:2px solid #ff5252;border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.7;">
🔴 <b style="color:#ff5252;font-size:15px">GATILHO ARMADO — VENDER</b> às <b>{_hr}</b><br>
Preço: <b>{_pr:.2f}</b> · Alvo: <b style="color:#00e676">{_al:.2f}</b> (-{_pe["amp_fibo"]*1.61:.1f} pts) · Stop: <b style="color:#ff5252">{_stp:.2f}</b> (+{_pe["stop_pts"]} pts) · Score <b>{_sc}/{_scm}</b> · Limiar <b>{_lim}%</b>{_extra}
</div>''', unsafe_allow_html=True)
            elif _a in ["compra","venda"] and _pr > 0:
                # Aguardando: mostra o que falta e a projeção pretendida
                _al, _stp = _fmt_alvo_stop(_a, _pr, _pe)
                _dir_txt = "COMPRAR" if _a == "compra" else "VENDER"
                _cor_dir = "#00e676" if _a == "compra" else "#ff5252"
                _faltas_html = "<br>".join([f"⏳ {f}" for f in _falta_lst[:3]])
                _extra = f"<br>Padrão detectado: <b>{_pad}</b>" if _pad and _pad != "nenhum" else ""
                _est_esp = _ctx.get("estrategia_especial_nome","Nenhuma")
                if _est_esp and _est_esp != "Nenhuma":
                    _extra += f'<br>⭐ <b style="color:#ffd740">{_est_esp}</b>'
                st.markdown(f'''<div style="background:linear-gradient(135deg,#332200,#1a1100);border:2px solid #ffd740;border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.7;">
🟡 <b style="color:#ffd740;font-size:15px">AGUARDAR</b> — pretensão: <b style="color:{_cor_dir}">{_dir_txt}</b> às <b>{_hr}</b><br>
Se armar em <b>{_pr:.2f}</b> → Alvo: <b style="color:#00e676">{_al:.2f}</b> · Stop: <b style="color:#ff5252">{_stp:.2f}</b> · Score <b>{_sc}/{_scm}</b>{_extra}<br>
<b>Condições pendentes:</b><br>{_faltas_html}
</div>''', unsafe_allow_html=True)
            else:
                _mot = _ctx.get("motivo_objetivo","Sem confluência técnica no momento.")
                st.markdown(f'''<div style="background:#1a1f2e;border:1px solid #2d3561;border-radius:10px;padding:12px 16px;font-size:13px;">
⚪ <b style="color:#8892a4">ESPERAR</b> — {_mot} · Preço: <b>{_pr:.2f}</b> · Hora: <b>{_hr}</b>
</div>''', unsafe_allow_html=True)
        else:
            st.info("Clique em ▶️ Executar Análise para gerar o resumo previsional.")

    with col_agentes:
        render_book_profundidade(
            st.session_state.get("ultimos_agentes", {}),
            num(st.session_state.get("ultimos_dados_tela", {}).get("preco_atual", 0)),
            max_niveis=6)
        st.markdown("")
        _ag = st.session_state.get("ultimos_agentes", {})
        if _ag:
            # Ofertantes de compra e venda (lista de dicts {agente, preco, qtde})
            _ofc = _ag.get("ofertantes_compra", []) or []
            _ofv = _ag.get("ofertantes_venda", []) or []
            _liq_forte = _ag.get("liquidez_forte", []) or []
            _saldo = str(_ag.get("saldo_agentes", "neutro")).lower()
            _pr_atual = num(st.session_state.ultimos_dados_tela.get("preco_atual", 0))

            # Fallback 1: reaproveitar liquidez_forte separando por tipo
            if not _ofc and not _ofv and _liq_forte:
                for _l in _liq_forte:
                    _t = str(_l.get("tipo","")).lower()
                    _item = {"agente": _l.get("agente","?"), "preco": num(_l.get("preco",0)), "qtde": int(_l.get("qtde",0) or 0)}
                    if _t == "compra": _ofc.append(_item)
                    elif _t == "venda": _ofv.append(_item)

            # Fallback 2: se ainda vazio, usar top_compradores/top_vendedores (só nomes)
            _top_c = _ag.get("top_compradores", []) or []
            _top_v = _ag.get("top_vendedores", []) or []
            if not _ofc and _top_c:
                _ofc = [{"agente": str(n), "preco": 0, "qtde": 0} for n in _top_c[:3]]
            if not _ofv and _top_v:
                _ofv = [{"agente": str(n), "preco": 0, "qtde": 0} for n in _top_v[:3]]

            # Ordena por quantidade (maior primeiro) e pega top 3 de cada lado
            _ofc = sorted(_ofc, key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[:3]
            _ofv = sorted(_ofv, key=lambda x: int(x.get("qtde",0) or 0), reverse=True)[:3]

            def _limpar_agente(nome):
                """Devolve "" quando nao ha nome real de corretora."""
                if not nome: return ""
                _n = str(nome).strip()
                _bad = ["nao identificado", "não identificado", "n/a", "?", "unknown",
                        "desconhecido", "-", "", "book", "agregado", "none", "null"]
                if _n.lower() in _bad: return ""
                return _n[:20]

            # A IA informa se o painel lido tinha coluna de nomes de corretoras
            _tem_nomes = bool(_ag.get("tem_nomes_agentes", False))
            if not _tem_nomes:
                _tem_nomes = any(_limpar_agente(o.get("agente","")) for o in (_ofc + _ofv))

            def _fmt_ofertantes(lst, cor, fallback_nomes=None):
                if not lst:
                    return '<span style="color:#8892a4;font-style:italic;">sem ofertantes detectados</span>'
                linhas = []
                for _o in lst:
                    _nm = _limpar_agente(_o.get("agente",""))
                    _pr = num(_o.get("preco",0))
                    _qt = int(_o.get("qtde",0) or 0)
                    if not _nm and fallback_nomes:
                        _i = min(len(linhas), len(fallback_nomes)-1)
                        _nm = _limpar_agente(fallback_nomes[_i]) if _i < len(fallback_nomes) else ""
                    _suf = f' · <span style="color:#c0c0c0">{_nm}</span>' if _nm else ''
                    if _pr > 0 and _qt > 0:
                        linhas.append(f'<span style="color:{cor}"><b>{_qt}</b></span> @ <b>{_pr:.2f}</b>{_suf}')
                    elif _pr > 0:
                        linhas.append(f'<b>{_pr:.2f}</b>{_suf}')
                    elif _qt > 0:
                        linhas.append(f'<span style="color:{cor}"><b>{_qt}</b></span>{_suf}')
                    elif _nm:
                        linhas.append(f'<span style="color:{cor}">●</span> <b>{_nm}</b>')
                return "<br>".join(linhas) if linhas else '<span style="color:#8892a4;font-style:italic;">sem ofertantes detectados</span>'

            _html_compra = _fmt_ofertantes(_ofc, "#00e676")
            _html_venda = _fmt_ofertantes(_ofv, "#ff5252")

            # Cor do saldo
            _cor_saldo = "#00e676" if _saldo == "comprador" else ("#ff5252" if _saldo == "vendedor" else "#8892a4")
            _emoji_saldo = "🟢" if _saldo == "comprador" else ("🔴" if _saldo == "vendedor" else "⚪")

            # Recomendação com base na proximidade do preço às ofertas mais fortes
            _reco = "Aguarde aproximação do preço às zonas de liquidez para avaliar rejeição."
            if _pr_atual > 0 and (_ofc or _ofv):
                _melhor_compra = _ofc[0] if _ofc else None
                _melhor_venda = _ofv[0] if _ofv else None
                if _melhor_compra and abs(_pr_atual - num(_melhor_compra.get("preco",0))) <= 3.0:
                    _reco = f"🟢 Preço colado em oferta forte de COMPRA ({_melhor_compra.get('agente','?')} com {_melhor_compra.get('qtde',0)} @ {num(_melhor_compra.get('preco',0)):.2f}). Monitore rejeição para buscar compra."
                elif _melhor_venda and abs(_pr_atual - num(_melhor_venda.get("preco",0))) <= 3.0:
                    _reco = f"🔴 Preço colado em oferta forte de VENDA ({_melhor_venda.get('agente','?')} com {_melhor_venda.get('qtde',0)} @ {num(_melhor_venda.get('preco',0)):.2f}). Monitore rejeição para buscar venda."

            # Card duplicado removido: a escada acima ja mostra preco x agente.
            _reco_txt = ("✅ Fluxo validado na direção do gatilho."
                         if st.session_state.get("ultimo_status_gatilho") == "ARMADO" else _reco)
            st.markdown(f'<div style="background:#161b2b;border-left:3px solid #ffd740;'
                        f'border-radius:8px;padding:9px 13px;font-size:13px;margin-top:8px;'
                        f'color:#e8ecf3;">{_reco_txt}</div>', unsafe_allow_html=True)
        else:
            st.info("Os maiores ofertantes de liquidez aparecem aqui após a primeira análise.")

    _intervalo_ciclo = intervalo_analise_atual()
    st.session_state["intervalo_ciclo_atual"] = _intervalo_ciclo
    _decorrido = agora - st.session_state.ultimo_ciclo_analise
    st.session_state["segundos_proxima_analise"] = max(0, int(_intervalo_ciclo - _decorrido))
    # TRAVA DURA: o rerun do Streamlit acontece a cada 5 s e nao autoriza
    # analise. Somente duas origens disparam ciclo automatico:
    #   1. o relogio de 300 s (sempre, em qualquer horario)
    #   2. o disparo de 15 s apos o anuncio de um indicador da agenda
    _ciclo_vencido = _decorrido >= _intervalo_ciclo

    # ---- JANELA OPERACIONAL: 08:55 as 18:10 ----
    # Ligar as 07h nao inicia o ciclo. O app faz UMA leitura de verificacao e
    # dorme ate as 08:55; depois das 18:10 encerra sozinho.
    _janela = estado_janela_operacional()
    st.session_state["estado_janela"] = _janela
    _na_janela = bool(_janela["dentro"])
    _lig_pendente = (st.session_state.analise_automatica and not _na_janela
                     and precisa_leitura_de_ligacao())

    _disp_anuncio, _disp_chave, _disp_evento = (False, "", "")
    if st.session_state.analise_automatica and _na_janela:
        try:
            _disp_anuncio, _disp_chave, _disp_evento = disparo_pos_anuncio()
        except Exception:
            _disp_anuncio, _disp_chave, _disp_evento = (False, "", "")

    rodar_auto = st.session_state.analise_automatica and (
        (_na_janela and (_ciclo_vencido or _disp_anuncio)) or _lig_pendente)
    st.session_state["origem_ciclo_atual"] = (
        "ligacao" if _lig_pendente else
        "anuncio" if (_disp_anuncio and not _ciclo_vencido) else "ciclo_5min")

    if not _na_janela:
        # Em repouso o contador da proxima analise mostra a abertura da janela.
        st.session_state["segundos_proxima_analise"] = int(
            _janela["minutos_para_abrir"] * 60) if _janela["fase"] == "pre" else 0

    if _disp_anuncio:
        # A analise pos-anuncio precisa do dado fresco. A coleta respeita o cache
        # por indicador, entao o custo e uma requisicao por indicador vencido.
        try:
            atualizar_macro_agendado(forcar=True)
        except Exception:
            pass
        st.session_state["ultimo_disparo_anuncio"] = (
            f"{datetime.now().strftime('%H:%M:%S')} — {_disp_evento}")

    # A leitura MANUAL disparada no meio do ciclo de 300 s informa, mas nao
    # reclassifica: foi uma leitura de 68 s que virou o regime no replay 14/08.
    # A analise disparada pelo anuncio e legitima e ENTRA na serie de historico,
    # mesmo caindo antes dos 300 s. So a leitura manual avulsa fica de fora.
    # A leitura de LIGACAO e verificacao de sistema, nao leitura de mercado:
    # informa o painel mas nao entra na serie de momentum.
    st.session_state["leitura_fora_de_ciclo"] = bool(
        _lig_pendente or (
            rodar and not rodar_auto and not _disp_anuncio
            and _decorrido < (FRACAO_CICLO_LEITURA_VALIDA * _intervalo_ciclo))
    )

    if rodar or rodar_auto:
        if not CHAVE_OPENROUTER:
            st.error("Defina a variável de ambiente OPENROUTER_API_KEY antes de executar o app.")
        else:
            with st.spinner("Analisando..."):
                img, msg = executar_analise()
            st.session_state.ultimo_ciclo_analise = agora
            if _disp_anuncio and _disp_chave:
                registrar_disparo_anuncio(_disp_chave)
            if _lig_pendente:
                registrar_leitura_de_ligacao()
            # Em modo replay, avança automaticamente 10 minutos a cada análise
            # Avanco cego de +10 min: so quando o usuario pedir E a tela nao tiver relogio legivel
            _origem = str(st.session_state.get("ultimos_dados_tela", {}).get("hora_replay_origem", "manual"))
            if (st.session_state.modo_replay
                    and st.session_state.get("avancar_replay_auto", False)
                    and _origem != "tela"
                    and st.session_state.get("replay_hora")):
                try:
                    h, m = map(int, str(st.session_state.get("replay_hora","09:00")).strip().split(":"))
                    total = h * 60 + m + 10
                    if total >= 24*60: total -= 24*60
                    _set_state("replay_hora", f"{total//60:02d}:{total%60:02d}")
                    _set_state("replay_seq", st.session_state.get("replay_seq", 0) + 1)
                except Exception:
                    pass
            if img is None:
                st.error(msg)
            else:
                st.success(msg)
                st.image(img, width=1100)


    st.markdown('<div class="section-title">📊 Níveis operacionais e leitura completa</div>', unsafe_allow_html=True)
    # --- Leitura atual ---
    st.markdown('<div class="section-title">📊 Última Leitura Automática</div>', unsafe_allow_html=True)
    if st.session_state.ultimos_dados_tela:
        dt2 = st.session_state.ultimos_dados_tela
        ignorar_m = st.session_state.modo_replay and not st.session_state.usar_macro_no_replay
        ctx = classificar_contexto(dt2, ler_fechamento_anterior() if not ignorar_m else None, ignorar_m)

        col_r1,col_r2,col_r3,col_r4,col_r5 = st.columns(5)
        col_r1.markdown(f'<div class="metric-card"><div class="label">Regime</div><div class="value blue">{ctx["regime"]}</div></div>', unsafe_allow_html=True)
        col_r2.markdown(f'<div class="metric-card"><div class="label">Ação Objetiva</div><div class="value {"green" if ctx["acao_objetiva"]=="compra" else "red" if ctx["acao_objetiva"]=="venda" else "gold"}">{ctx["acao_objetiva"].upper()}</div></div>', unsafe_allow_html=True)
        col_r3.markdown(f'<div class="metric-card"><div class="label">Score</div><div class="value blue">{ctx["score"]}/{ctx["score_minimo_usado"]}</div></div>', unsafe_allow_html=True)
        col_r4.markdown(f'<div class="metric-card"><div class="label">Estratégia Auto</div><div class="value gold">{ctx["estrategia"]}</div></div>', unsafe_allow_html=True)
        
        # Limiar de segurança
        lim = ctx["limiar"]
        lim_class = "green" if lim >= 70 else ("gold" if lim >= 40 else "red")
        lim_txt = "FORTE" if lim >= 70 else ("MÉDIO" if lim >= 40 else "FRACO")
        col_r5.markdown(f'<div class="metric-card"><div class="label">Limiar Segurança</div><div class="value {lim_class}">{lim}% {lim_txt}</div></div>', unsafe_allow_html=True)

        st.markdown(f'<div class="regime-box">🎯 <b>Viés atual:</b> {ctx["vies"]} &nbsp;|&nbsp; <b>Motivo:</b> {ctx["motivo_objetivo"]}</div>', unsafe_allow_html=True)

        # O que falta para o gatilho
        _falta = ctx.get("falta_para_gatilho", [])
        _prox  = ctx.get("condicao_mais_proxima", [])
        if _falta:
            st.markdown("**⚠️ O que falta para armar o gatilho:**")
            for _it in _falta:
                st.markdown(f'<div style="background:#2d1a00;border-left:3px solid #ffd740;border-radius:6px;padding:6px 12px;margin:3px 0;font-size:13px;color:#ffd740;">⏳ {_it}</div>', unsafe_allow_html=True)
        if _prox:
            for _it in _prox:
                st.markdown(f'<div style="background:#001a2d;border-left:3px solid #40c4ff;border-radius:6px;padding:6px 12px;margin:3px 0;font-size:13px;color:#40c4ff;">📍 {_it}</div>', unsafe_allow_html=True)

        # Pontos fortes Fibonacci próximos ao preço atual
        _fib_p = ler_fechamento_anterior().get("fibonacci_diario", {})
        _preco_p = num(st.session_state.ultimos_dados_tela.get("preco_atual", 0))
        if _fib_p and _preco_p > 0:
            _nf = {"38,2%": _fib_p.get("nivel_382",0), "50%": _fib_p.get("nivel_50",0), "61,8%": _fib_p.get("nivel_618",0)}
            _pf = [(k,v) for k,v in _nf.items() if v and abs(_preco_p-v)<=5.0]
            if _pf:
                st.markdown("**⭐ Pontos fortes Fibonacci próximos ao preço atual:**")
                for _k,_v in _pf:
                    _d = round(_preco_p-_v, 2)
                    _c = "#00e676" if _d>0 else "#ff5252"
                    st.markdown(f'<div style="background:#0d2200;border-left:3px solid #00e676;border-radius:6px;padding:6px 12px;margin:3px 0;font-size:13px;"><span style="color:#00e676">⭐ Fib {_k}: {_v}</span> &nbsp;|&nbsp; dist: <span style="color:{_c}">{_d:+.2f} pts</span></div>', unsafe_allow_html=True)

        # Distâncias
        dist_data = {
            "VWAP": ctx["dist_vwap"], "Ajuste": ctx["dist_ajuste"],
            "MM9": ctx["dist_mm9"], "MM20": ctx["dist_mm20"],
            "MM50": ctx["dist_mm50"], "MM200": ctx["dist_mm200"],
        }
        col_d = st.columns(6)
        for i,(k,v) in enumerate(dist_data.items()):
            cor = "green" if v > 0 else "red"
            col_d[i].markdown(f'<div class="metric-card"><div class="label">Dist. {k}</div><div class="value {cor}">{v:+.1f}</div></div>', unsafe_allow_html=True)

        # ============ VARAL DE CONTRATOS ============
        st.markdown('<div class="section-title">🧵 Varal de Contratos (Escalonamento de Posição)</div>', unsafe_allow_html=True)
        col_var1, col_var2 = st.columns([1, 4])
        with col_var1:
            st.number_input("Contratos totais", key="varal_contratos_totais", min_value=1, max_value=50, step=1)
            st.checkbox("Ativar varal", key="varal_ativo")
        with col_var2:
            if st.session_state.varal_ativo:
                _fech_var = ler_fechamento_anterior() if not (st.session_state.modo_replay and not st.session_state.usar_macro_no_replay) else None
                varal_info = calcular_varal_contratos_por_nivel(
                    st.session_state.ultimos_dados_tela, ctx, _fech_var,
                    contratos_totais=st.session_state.varal_contratos_totais
                )
                if varal_info["status"] == "armado":
                    _dir = varal_info["direcao"]
                    _cor_dir = "#00e676" if _dir == "COMPRA" else "#ff5252"
                    _emoji = "🟢" if _dir == "COMPRA" else "🔴"
                    st.markdown(f'''<div style="background:#1a1f2e;border-left:4px solid {_cor_dir};border-radius:6px;padding:8px 14px;margin-bottom:8px;font-size:13px;">
{_emoji} <b style="color:{_cor_dir}">{_dir}</b> · <b>{varal_info["contratos_totais"]}</b> contratos escalonados · Preço médio potencial: <b>{varal_info["preco_medio_potencial"]:.2f}</b>
</div>''', unsafe_allow_html=True)
                    cols_v = st.columns(len(varal_info["niveis"]))
                    for i, item in enumerate(varal_info["niveis"]):
                        if "Stop" in item["tipo"]:
                            cor_b, cor_v = "#ff5252", "red"
                        elif "Imediata" in item["tipo"]:
                            cor_b, cor_v = ("#00e676" if _dir == "COMPRA" else "#ff5252"), ("green" if _dir == "COMPRA" else "red")
                        else:
                            cor_b, cor_v = "#ffd740", "gold"
                        cols_v[i].markdown(f'''<div class="metric-card" style="border: 1px solid {cor_b};">
<div class="label">{item["nivel"]}</div>
<div class="value {cor_v}">{item["preco"]:.2f}</div>
<div style="font-size:11px; color:#8892a4; margin-top:4px;"><b>{item["contratos"]}</b> contratos<br><span style="font-size:10px;">{item["tipo"]}</span><br><span style="font-size:10px;color:#40c4ff;">📍 {item["referencia"]}</span></div>
</div>''', unsafe_allow_html=True)
                else:
                    st.info(f"⏳ {varal_info['mensagem']}")
            else:
                st.caption("Varal de contratos desativado. Marque a checkbox ao lado para ativar o escalonamento.")
    else:
        st.info("Nenhuma leitura realizada ainda. Clique em **Executar Análise**.")


    st.markdown('<div class="section-title">🗂️ Apoio, configurações e diagnóstico</div>', unsafe_allow_html=True)
    with st.expander("🏅 Ranking histórico dos indicadores (base dos pesos)", expanded=False):
        render_ranking_indicadores()

    with st.expander("📁 Contexto do dia — viés anterior, Fibonacci e extremos", expanded=False):
        # --- Viés do dia anterior ---
        st.markdown('<div class="section-title">📌 Viés do Dia Anterior</div>', unsafe_allow_html=True)
        fech = ler_fechamento_anterior()
        vies_c = {"comprador":"🟢","vendedor":"🔴","neutro":"🟡","indefinido":"⚪"}.get(fech.get("vies","indefinido"),"⚪")
        col_v1,col_v2,col_v3,col_v4,col_v5 = st.columns(5)
        col_v1.markdown(f'<div class="metric-card"><div class="label">Viés</div><div class="value">{vies_c} {fech.get("vies","N/A").upper()}</div></div>', unsafe_allow_html=True)
        col_v2.markdown(f'<div class="metric-card"><div class="label">Preço Fech.</div><div class="value blue">{fech.get("preco","N/A")}</div></div>', unsafe_allow_html=True)
        col_v3.markdown(f'<div class="metric-card"><div class="label">Ajuste Ant.</div><div class="value blue">{fech.get("ajuste","N/A")}</div></div>', unsafe_allow_html=True)
        col_v4.markdown(f'<div class="metric-card"><div class="label">VWAP Ant.</div><div class="value blue">{fech.get("vwap","N/A")}</div></div>', unsafe_allow_html=True)
        col_v5.markdown(f'<div class="metric-card"><div class="label">Data Ref.</div><div class="value">{fech.get("data","N/A")}</div></div>', unsafe_allow_html=True)

        # Fibonacci do dia anterior como zonas de segurança
        fib_ant = fech.get("fibonacci_diario", {})
        if fib_ant:
            st.markdown('<div class="section-title">📐 Zonas Fibonacci do Dia Anterior (Suporte/Resistência)</div>', unsafe_allow_html=True)
            st.caption(f"Amplitude: {fib_ant.get('amp','N/A')} pts | Máx: {fib_ant.get('nivel_0','N/A')} | Mín: {fib_ant.get('nivel_100','N/A')}")
            cf1,cf2,cf3,cf4,cf5 = st.columns(5)
            def fib_card(col, label, valor, forte=False):
                cor = "gold" if forte else "blue"
                col.markdown(f'<div class="metric-card"><div class="label">{"⭐ " if forte else ""}{label}</div><div class="value {cor}">{valor}</div></div>', unsafe_allow_html=True)
            fib_card(cf1, "23.6%", fib_ant.get('nivel_236','N/A'))
            fib_card(cf2, "38.2% 🎯", fib_ant.get('nivel_382','N/A'), forte=True)
            fib_card(cf3, "50% 🎯", fib_ant.get('nivel_50','N/A'), forte=True)
            fib_card(cf4, "61.8% 🎯", fib_ant.get('nivel_618','N/A'), forte=True)
            fib_card(cf5, "78.6%", fib_ant.get('nivel_786','N/A'))
            st.caption("🎯 = Zonas fortes de suporte/resistência. Gatilhos próximos dessas zonas têm maior confiabilidade.")
        else:
            st.info("ℹ️ Registre o fechamento do dia para gerar as zonas Fibonacci de amanhã.")

        col_reg1, col_reg2 = st.columns([2,1])
        with col_reg1:
            st.checkbox("⏺️ Registrar fechamento automaticamente na próxima análise", key="registrar_fechamento_ativo")
        with col_reg2:
            if st.button("💾 Registrar fechamento agora"):
                if st.session_state.ultimos_dados_tela:
                    dt = st.session_state.ultimos_dados_tela
                    m = ler_dados_macro()
                    mx_usar = st.session_state.get("max_dia_manual",0.0) or num(dt.get("maxima"))
                    mn_usar = st.session_state.get("min_dia_manual",0.0) or num(dt.get("minima"))
                    d = salvar_fechamento_dia(num(dt.get("preco_atual")),num(dt.get("ajuste")),num(dt.get("vwap")),num(m.get("DXY")),num(m.get("EWZ")),num(m.get("VIX")),mx_usar,mn_usar)
                    st.success(f"Registrado: viés={d['vies']} | preço={d['preco']} | 50%={d.get('fibonacci_diario',{}).get('nivel_50','N/A')}")
                else:
                    st.warning("Execute uma análise primeiro.")

        st.markdown("**📐 Máxima e Mínima do dia anterior (corrigir manualmente se necessário):**")
        col_mx, col_mn, col_fib = st.columns(3)
        with col_mx:
            st.number_input("Máxima do dia anterior", key="max_dia_manual", step=0.5,
                            help="Se 0, usa a máxima capturada da tela automaticamente")
        with col_mn:
            st.number_input("Mínima do dia anterior", key="min_dia_manual", step=0.5,
                            help="Se 0, usa a mínima capturada da tela automaticamente")
        with col_fib:
            if st.button("🔄 Recalcular Fibonacci agora"):
                mx = st.session_state.get("max_dia_manual",0.0)
                mn = st.session_state.get("min_dia_manual",0.0)
                if mx > 0 and mn > 0 and mx > mn:
                    fib_novo = calcular_fibonacci_diario(mx, mn)
                    fech_atual = ler_fechamento_anterior()
                    fech_atual["maxima_dia"] = mx
                    fech_atual["minima_dia"] = mn
                    fech_atual["fibonacci_diario"] = fib_novo
                    try:
                        with open(FECHAMENTO_JSON,"w",encoding="utf-8") as _f:
                            json.dump(fech_atual,_f,ensure_ascii=False,indent=2)
                        st.success(f"✅ 38,2%={fib_novo.get('nivel_382','?')} | 50%={fib_novo.get('nivel_50','?')} | 61,8%={fib_novo.get('nivel_618','?')}")
                    except Exception as _e:
                        st.error(f"Erro: {_e}")
                else:
                    st.warning("Informe máxima > mínima > 0")


    # --- Configuracoes ---
    with st.expander("⚙️ Configurações", expanded=False):
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            st.checkbox("🔄 Análise automática a cada 5 min", key="analise_automatica")
            try:
                _jan_p = st.session_state.get("estado_janela") or estado_janela_operacional()
                if _jan_p.get("dentro"):
                    st.caption(
                        f"🟢 Janela operacional {_jan_p['inicio']}–{_jan_p['fim']} — ativa")
                else:
                    st.caption(f"😴 {_jan_p.get('resumo', '')}")
                _hlig = st.session_state.get("hora_leitura_ligacao", "")
                if _hlig:
                    st.caption(f"✅ Leitura de verificação às {_hlig}")
            except Exception:
                pass
            try:
                _prox_ev = proximo_evento_macro()
                if _prox_ev.get("nome"):
                    st.caption(
                        f"📅 {_prox_ev['nome']} às {_prox_ev['hora']} "
                        f"(em {_prox_ev['faltam']} min) — análise extra "
                        f"{SEGUNDOS_APOS_ANUNCIO}s após o anúncio")
                _ult_disp = st.session_state.get("ultimo_disparo_anuncio", "")
                if _ult_disp:
                    st.caption(f"⚡ Último disparo por anúncio: {_ult_disp}")
                _rms = int(st.session_state.get("refresh_ms_atual", INTERVALO_REFRESH_APP_MS))
                st.caption(
                    f"🕒 Tela atualiza a cada {_rms // 1000}s · análise a cada "
                    f"{INTERVALO_ANALISE_SEGUNDOS // 60} min"
                    + (" · modo fino (anúncio próximo)"
                       if _rms == INTERVALO_REFRESH_ANUNCIO_MS else ""))
            except Exception:
                pass
            st.checkbox("⚡ Disparo automático", key="disparo_automatico")
            st.checkbox("🔒 Bloquear gatilho repetido", key="bloquear_gatilho_repetido")
            st.checkbox("🔔 Alertas sonoros", key="som_ativo")
            st.checkbox("🚨 Alerta de mudança brusca de tendência", key="som_mudanca_brusca")
        st.markdown("---")
        if st.button("💾 Salvar e Aplicar Configurações", use_container_width=True):
            st.success("Configurações atualizadas com sucesso!")
            st.rerun()
            with st.expander("🇺🇸 PMI dos EUA (Calendário Econômico)", expanded=False):
                st.caption("Informe os valores do dia. Acima de 52 favorece alta do dólar; abaixo de 48 pressiona para baixo.")
                _p1, _p2 = st.columns(2)
                with _p1:
                    st.number_input("PMI Serviços ISM", key="pmi_ism_servicos", step=0.1, format="%.1f")
                    st.number_input("PMI Manufatura", key="pmi_manufatura", step=0.1, format="%.1f")
                with _p2:
                    st.number_input("PMI Serviços S&P", key="pmi_sp_servicos", step=0.1, format="%.1f")
                    st.number_input("PMI Composto", key="pmi_composto", step=0.1, format="%.1f")
                _pv = peso_pmi_eua(ler_dados_macro())
                if _pv.get("pmi"):
                    _cor_p = "#00e676" if _pv["peso"] > 0 else ("#ff5252" if _pv["peso"] < 0 else "#8892a4")
                    st.markdown(f'<div style="background:#1a1f2e;border-left:3px solid {_cor_p};border-radius:6px;'
                                f'padding:8px 12px;font-size:12px;">🇺🇸 <b style="color:{_cor_p}">{_pv["descricao"]}</b><br>'
                                f'Peso no score: <b>{_pv["peso"]:+d}</b></div>', unsafe_allow_html=True)
            _ct1, _ct2 = st.columns(2)
            if _ct1.button("🔊 Testar som compra", use_container_width=True):
                disparar_alarme("Gatilho armado. Compra.", tipo="gatilho_compra")
            if _ct2.button("🔊 Testar som venda", use_container_width=True):
                disparar_alarme("Gatilho armado. Venda.", tipo="gatilho_venda")
            _ct3, _ct4 = st.columns(2)
            if _ct3.button("🚨 Testar reversão", use_container_width=True):
                disparar_alarme("Atencao. Mudanca brusca de tendencia.", tipo="reversao")
            if _ct4.button("⚡ Testar alerta máximo", use_container_width=True):
                disparar_alarme("Alerta maximo. Movimento brusco detectado.", tipo="alerta_maximo")

        with col_c2:
            st.checkbox("🎬 Modo Replay", key="modo_replay")
            if st.session_state.modo_replay:
                _dk = f"replay_data_w{st.session_state.get('replay_seq', 0)}"
                _dval = st.text_input("Data replay (YYYY-MM-DD)", value=st.session_state.replay_data, key=_dk)
                if _dval != st.session_state.replay_data:
                    st.session_state.replay_data = _dval
                # Chave dinâmica: ao avançar, a chave muda e o widget recarrega o novo valor
                _rk = f"replay_hora_w{st.session_state.get('replay_seq', 0)}"
                _hval = st.text_input("Hora replay (HH:MM)", value=st.session_state.replay_hora, key=_rk)
                if _hval != st.session_state.replay_hora:
                    st.session_state.replay_hora = _hval
                st.checkbox("⏩ Avançar +10 min a cada análise (só se a tela não tiver relógio)",
                            key="avancar_replay_auto")
                _org = str(st.session_state.get("ultimos_dados_tela", {}).get("hora_replay_origem", ""))
                _hr_real = str(st.session_state.get("ultimos_dados_tela", {}).get("hora_replay", ""))
                if _org == "tela":
                    st.success(f"🎯 Relógio lido da tela: **{st.session_state.replay_data} {_hr_real}**")
                elif _org == "manual":
                    st.warning(f"⚠️ Relógio não lido da tela — usando campo manual: **{st.session_state.replay_data} {st.session_state.replay_hora}**")
                else:
                    st.caption(f"⏱️ Timestamp previsto: **{st.session_state.replay_data} {st.session_state.replay_hora}**")
                st.checkbox("📊 Usar dados macro no replay", key="usar_macro_no_replay")
                if not st.session_state.usar_macro_no_replay:
                    st.caption("💡 Replay sem macro: análise puramente técnica da tela.")

        with col_c3:
            st.selectbox("Estratégia base", ["Conservador","Agressividade Média","Agressividade Alta"], key="estrategia_operacional")
            pe = ESTRATEGIAS[st.session_state.estrategia_operacional]
            st.markdown(f"""
<div style="background:{pe['cor']}22;border-left:3px solid {pe['cor']};border-radius:6px;padding:8px 12px;font-size:12px;margin-top:6px;">
<b style="color:{pe['cor']}">{st.session_state.estrategia_operacional}</b><br>
{pe['descricao']}<br>
Score mín: {pe['score_minimo_base']}/7 | RR mín: {pe['rr_minimo']} | Margem VWAP: {pe['margem_vwap']} pts
</div>""", unsafe_allow_html=True)

        # COPIE A PARTIR DAQUI (Alinhado com o "with col_c3:")
        st.markdown("---")
        if st.button("💾 Salvar e Aplicar Configurações", use_container_width=True, key="btn_salvar_configs_unico"):
            st.success("Configurações atualizadas!")
            st.rerun()

    # --- Diagnóstico ---
    # Faixa de alerta de mudanca brusca
    _mb = st.session_state.get("ultima_mudanca_brusca", "")
    if _mb:
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#3d1a00,#1f0d00);border:2px solid #ff9800;'
            f'border-radius:10px;padding:12px 16px;font-size:14px;margin:8px 0;">'
            f'🚨 <b style="color:#ff9800;font-size:15px">MUDANÇA BRUSCA DE TENDÊNCIA</b><br>'
            f'<span style="color:#ffd9a0">{_mb}</span></div>',
            unsafe_allow_html=True)

    # Historico de alertas sonoros da sessao
    _ha = st.session_state.get("historico_alertas", [])
    if _ha:
        with st.expander(f"🔔 Últimos alertas sonoros ({len(_ha)})", expanded=False):
            _icones = {"gatilho_compra": "🟢", "gatilho_venda": "🔴",
                       "reversao": "🔄", "alerta_maximo": "⚡", "aviso": "🔔"}
            for _a in _ha[:10]:
                _ic = _icones.get(_a.get("tipo", "aviso"), "🔔")
                st.markdown(
                    f'<div style="background:#1a1f2e;border-left:3px solid #40c4ff;border-radius:6px;'
                    f'padding:6px 12px;margin:3px 0;font-size:12px;">'
                    f'{_ic} <b>{_a.get("hora","")}</b> · {_a.get("texto","")}</div>',
                    unsafe_allow_html=True)

    # Card de momentum e PMI
    _dtm = st.session_state.get("ultimos_dados_tela", {})
    if _dtm:
        _igm = st.session_state.modo_replay and not st.session_state.usar_macro_no_replay
        _cm = classificar_contexto(_dtm, ler_fechamento_anterior() if not _igm else None, _igm)
        _mo = _cm.get("momentum", "neutro")
        _d1 = _cm.get("delta_preco", 0); _d3 = _cm.get("delta_3", 0)
        _prg = _cm.get("pos_range", 50); _corr = _cm.get("corrigido_por_momentum", False)
        _pmiv = _cm.get("pmi_valor"); _pmid = _cm.get("pmi_descricao", "")
        _cores_m = {"alta_forte": "#00e676", "alta": "#66bb6a", "neutro": "#8892a4",
                    "baixa": "#ef5350", "baixa_forte": "#ff5252"}
        _cm_cor = _cores_m.get(_mo, "#8892a4")
        _icone_m = {"alta_forte": "🚀", "alta": "📈", "neutro": "➖",
                    "baixa": "📉", "baixa_forte": "⚠️"}.get(_mo, "➖")
        _corr_html = '<br>🔄 <b style="color:#ffd740">Direção corrigida pelo momentum</b>' if _corr else ''
        _pmi_html = f'<br>🇺🇸 {_pmid}' if _pmiv else ''
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#0d1220,#1a1f2e);border:1px solid {_cm_cor};'
            f'border-radius:8px;padding:10px 14px;font-size:12px;margin:8px 0;">'
            f'{_icone_m} <b style="color:{_cm_cor}">Momentum: {_mo.upper()}</b> &nbsp;·&nbsp; '
            f'Última leitura: <b>{_d1:+.1f} pts</b> &nbsp;·&nbsp; 3 leituras: <b>{_d3:+.1f} pts</b> &nbsp;·&nbsp; '
            f'Posição no range do dia: <b>{_prg:.0f}%</b>{_corr_html}{_pmi_html}</div>',
            unsafe_allow_html=True)

    st.markdown('<div class="section-title">📋 Estado Atual</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="diag-box">{st.session_state.ultimo_diagnostico}</div>', unsafe_allow_html=True)

    # Card do motor de decisão (AutoProTradingDecisionEngine)
    _dt = st.session_state.get("ultimos_dados_tela", {})
    if _dt:
        _ig_m = st.session_state.modo_replay and not st.session_state.usar_macro_no_replay
        _ctx_m = classificar_contexto(_dt, ler_fechamento_anterior() if not _ig_m else None, _ig_m)
        _sc_orig = _ctx_m.get("score_original", 0)
        _sc_pond = _ctx_m.get("score_ponderado", 0)
        _dist_of = _ctx_m.get("distancia_maior_ofertante", 0)
        _sag = _ctx_m.get("saldo_agressao_pct", 50)
        _eng_st = _ctx_m.get("engine_status", "N/A")
        _eng_mt = _ctx_m.get("engine_motivo", "")
        _cor_eng = "#00e676" if _eng_st == "APROVADO" else "#ff5252"
        _dif_score = _sc_orig - _sc_pond
        _sinal = "−" if _dif_score > 0 else ("+" if _dif_score < 0 else "±0")
        st.markdown(f'''<div style="background:linear-gradient(135deg,#0d1220,#1a1f2e);border:1px solid {_cor_eng};border-radius:8px;padding:10px 14px;font-size:12px;margin-top:8px;">
🤖 <b style="color:{_cor_eng}">Motor de Decisão (AutoPro)</b> &nbsp;·&nbsp; Status: <b style="color:{_cor_eng}">{_eng_st}</b><br>
Score bruto: <b>{_sc_orig}</b> → Score ponderado: <b>{_sc_pond}</b> ({_sinal}{abs(_dif_score)}) &nbsp;·&nbsp; Dist. maior ofertante: <b>{_dist_of:.2f} pts</b> &nbsp;·&nbsp; Saldo agressão: <b>{_sag:.1f}%</b><br>
<span style="color:#8892a4;font-size:11px;">{_eng_mt}</span>
</div>''', unsafe_allow_html=True)
    st.caption(f"Última janela: {st.session_state.ultimo_titulo_capturado}")

    if st.session_state.get("ultimo_erro_ia"):
        st.warning(f"⚠️ Erro da IA: {st.session_state['ultimo_erro_ia']}")

    # Diagnostico das capturas SuperDom/T&T/Livro
    st.markdown('<div class="section-title">🔎 Capturas de Janelas Auxiliares</div>', unsafe_allow_html=True)
    col_cap1, col_cap2, col_cap3, col_cap4, col_cap5 = st.columns(5)
    _cor_ok = lambda ok: "#00e676" if ok else "#ff5252"
    
    # Recuperação segura dos logs do session_state (evita NameError)
    _log_sd = st.session_state.get("log_captura_SuperDom", "Não executado")
    _log_tt = st.session_state.get("log_captura_tt", "Não executado")
    _log_lv = st.session_state.get("log_captura_livro", "Não executado")
    _log_ag = st.session_state.get("log_captura_agentes", "Não executado")
    _log_tt_oo = st.session_state.get("log_captura_tt_oo", "Não executado")

    _ok_sd = "capturado" in _log_sd.lower()
    _ok_tt = "capturado" in _log_tt.lower()
    _ok_lv = "capturado" in _log_lv.lower()
    _ok_ag = ("capturado" in _log_ag.lower()) or ("via t&t" in _log_ag.lower())
    _origem_ag = st.session_state.get("origem_agentes", "")
    _rotulo_ag = "Agentes (T&T Ordem Original)" if _origem_ag.startswith("tape") else "Agentes (Negociação)"
    _ok_tt_oo = "capturado" in _log_tt_oo.lower() or "1ª janela" in _log_tt_oo.lower() or "(1ª" in _log_tt_oo.lower()

    col_cap1.markdown(f'<div style="background:#1a1f2e;border-left:3px solid {_cor_ok(_ok_sd)};border-radius:6px;padding:8px 12px;font-size:12px;">{"🟢" if _ok_sd else "🔴"} <b>SuperDom</b><br>{_log_sd[:150]}</div>', unsafe_allow_html=True)
    col_cap2.markdown(f'<div style="background:#1a1f2e;border-left:3px solid {_cor_ok(_ok_tt_oo)};border-radius:6px;padding:8px 12px;font-size:12px;">{"🟢" if _ok_tt_oo else "🔴"} <b>T&T Ordem Original</b><br>{_log_tt_oo[:150]}</div>', unsafe_allow_html=True)
    col_cap3.markdown(f'<div style="background:#1a1f2e;border-left:3px solid {_cor_ok(_ok_tt)};border-radius:6px;padding:8px 12px;font-size:12px;">{"🟢" if _ok_tt else "🔴"} <b>T&T Negócios</b><br>{_log_tt[:150]}</div>', unsafe_allow_html=True)
    col_cap4.markdown(f'<div style="background:#1a1f2e;border-left:3px solid {_cor_ok(_ok_lv)};border-radius:6px;padding:8px 12px;font-size:12px;">{"🟢" if _ok_lv else "🔴"} <b>Livro de Ofertas</b><br>{_log_lv[:150]}</div>', unsafe_allow_html=True)
    col_cap5.markdown(f'<div style="background:#1a1f2e;border-left:3px solid {_cor_ok(_ok_ag)};border-radius:6px;padding:8px 12px;font-size:12px;">{"🟢" if _ok_ag else "🔴"} <b>{_rotulo_ag}</b><br>{_log_ag[:150]}</div>', unsafe_allow_html=True)
    st.caption(f"Fonte usada para análise de fluxo: **{st.session_state.get('fonte_fluxo','—')}**")

    # Alerta se a IA de agentes nao esta trazendo dados uteis
    _ag_ult = st.session_state.get("ultimos_agentes", {})
    if _ag_ult:
        _ofc = _ag_ult.get("ofertantes_compra", []) or []
        _ofv = _ag_ult.get("ofertantes_venda", []) or []
        if not _ofc and not _ofv:
            st.warning("⚠️ Nenhum ofertante identificado. Deixe visível o T&T na aba **Ordem Original** (colunas Compradora / Vendedora / Agressor) — é dela que os agentes são extraídos neste layout.")

    # ============ TESTE DE CAPTURA DAS JANELAS ============
    with st.expander("🖥️ Testar captura das janelas (Gráfico, SuperDom, T&T, Livro)", expanded=False):
        st.caption("Método: BitBlt direto do desktop na região de cada janela — funciona em qualquer monitor, sem admin.")
        colt1, colt2, colt3, colt4, colt5 = st.columns(5)
        if colt1.button("📈 Gráfico"):
            _im, _ms = capturar_janela()
            if _im: st.image(_im, caption=f"Gráfico — {_ms}", width=700)
            else: st.error(_ms)
        if colt2.button("📊 SuperDom"):
            _im, _ms = capturar_SuperDom()
            if _im: st.image(_im, caption=f"SuperDom — {_ms}", width=700)
            else: st.error(_ms)
        if colt3.button("⏱️ Times & Trades"):
            _im, _ms = capturar_times_trades()
            if _im: st.image(_im, caption=f"T&T — {_ms}", width=700)
            else: st.error(_ms)
        if colt4.button("📚 Livro de Ofertas"):
            _im, _ms = capturar_livro_ofertas()
            if _im: st.image(_im, caption=f"Livro — {_ms}", width=700)
            else: st.error(_ms)
        if colt5.button("🎯 Tela completa Profit"):
            _im, _ms = capturar_tela_completa_profit()
            if _im: st.image(_im, caption=f"Tela completa — {_ms}", width=1000)
            else: st.error(_ms)
        colt6, colt7 = st.columns([1,1])
        if colt6.button("👥 Testar Agentes (Negociação/Pressão)"):
            _im, _ms = capturar_agentes()
            if _im: st.image(_im, caption=f"Agentes — {_ms}", width=700)
            else: st.error(_ms)
        if colt7.button("📜 Testar T&T Ordem Original"):
            _im, _ms = capturar_times_trades_ordem_original()
            if _im: st.image(_im, caption=f"T&T Ordem Original — {_ms}", width=700)
            else: st.error(_ms)

        if st.button("🪟 Listar TODAS as janelas visíveis (sem filtro)"):
            _todas_j = listar_todas_janelas_visiveis()
            if not _todas_j:
                st.error("Nenhuma janela visível detectada.")
            else:
                st.success(f"{len(_todas_j)} janelas visíveis detectadas:")
                st.dataframe(pd.DataFrame(_todas_j), width="stretch")
                st.caption("Copie os títulos das janelas do Profit e informe quais correspondem ao tape (Ordem Original), ao book e ao gráfico.")

        if st.button("🔍 Diagnosticar TODAS as janelas do Profit (debug)"):
            janelas_diag = diagnosticar_janelas_profit()
            if not janelas_diag:
                st.error("Nenhuma janela relacionada ao Profit encontrada no sistema.")
            else:
                st.success(f"Encontrei {len(janelas_diag)} janelas relacionadas:")
                _linhas_diag = []
                for j in janelas_diag:
                    try:
                        l, top, r, b = win32gui.GetWindowRect(j["hwnd"])
                        _linhas_diag.append({
                            "Título": j["titulo"][:70] or "(sem título)",
                            "Classe": j["classe"][:30],
                            "Left": l, "Top": top,
                            "Largura": r-l, "Altura": b-top,
                            "Área": j["area"], "hwnd": j["hwnd"],
                        })
                    except Exception:
                        _linhas_diag.append({
                            "Título": j["titulo"][:70] or "(sem título)",
                            "Classe": j["classe"][:30],
                            "Left": "?", "Top": "?", "Largura": "?", "Altura": "?",
                            "Área": j["area"], "hwnd": j["hwnd"],
                        })
                df_diag = pd.DataFrame(_linhas_diag)
                st.dataframe(df_diag, width='stretch', hide_index=True)

    with st.expander("🔍 Retorno bruto da IA"):
        st.text(st.session_state.get("ultimo_retorno_ia_bruto","") or "Nenhum retorno disponível.")

    with st.expander("🕵️ Tabela de Auditoria (Dados Lidos)", expanded=True):
        if st.session_state.get("ultimos_dados_tela"):
            # Transforma os dados em formato vertical para não cortar colunas
            dados_dict = st.session_state.ultimos_dados_tela
            df_auditoria = pd.DataFrame(list(dados_dict.items()), columns=["Campo da Tela", "Valor Extraído"])
            st.dataframe(df_auditoria, use_container_width=True, hide_index=True)
            
            # Mostra o parecer da IA
            _auditoria_texto = st.session_state.get("ultima_auditoria_ia", "Nenhuma auditoria registrada.")
            st.markdown(f"**Parecer da Auditoria (IA):**\n> {_auditoria_texto}")
        else:
            st.info("A tabela de auditoria aparecerá aqui após a primeira execução.")

    mac2 = ler_dados_macro()
    cols_mac = st.columns(9)
    for i,(k,label) in enumerate([("DXY","DXY"),("EWZ","EWZ"),("USDBRL","USD/BRL"),("PTAX","PTAX"),
                                    ("VIX","VIX"),("SPY","SPY"),("QQQ","QQQ"),("TLT","TLT"),("CL_OIL","Petróleo")]):
        cols_mac[i].markdown(f'<div class="metric-card"><div class="label">{label}</div><div class="value blue">{mac2.get(k,"N/A")}</div></div>', unsafe_allow_html=True)
    st.caption(f"Atualização macro: {mac2.get('timestamp','N/A')}")

    # --- Histórico ---
    st.markdown('<div class="section-title">📁 Histórico de Gatilhos</div>', unsafe_allow_html=True)
    if st.session_state.historico_trades:
        df_h = pd.DataFrame(st.session_state.historico_trades)
        if "DataRegistro" in df_h.columns:
            df_h["_ord"]=pd.to_datetime(df_h["DataRegistro"],errors="coerce")
            df_h=df_h.sort_values("_ord",ascending=False).drop(columns=["_ord"])

        col_f1,col_f2,col_f3,col_f4 = st.columns(4)
        with col_f1: fs = st.selectbox("Status",["Todos","ARMADO","BLOQUEADO","ESPERA"])
        with col_f2: ft = st.selectbox("Tipo",["Todos","COMPRA","VENDA","ESPERA"])
        with col_f3:
            ops_e=["Todos"]+(sorted(df_h["Estrategia"].dropna().unique().tolist()) if "Estrategia" in df_h.columns else [])
            fe = st.selectbox("Estratégia",ops_e)
        with col_f4:
            ops_r=["Todos"]+(sorted(df_h["Regime"].dropna().unique().tolist()) if "Regime" in df_h.columns else [])
            fr = st.selectbox("Regime",ops_r)

        df_f2 = df_h.copy()
        if fs!="Todos" and "StatusGatilho" in df_f2.columns: df_f2=df_f2[df_f2["StatusGatilho"]==fs]
        if ft!="Todos" and "Tipo" in df_f2.columns: df_f2=df_f2[df_f2["Tipo"]==ft]
        if fe!="Todos" and "Estrategia" in df_f2.columns: df_f2=df_f2[df_f2["Estrategia"]==fe]
        if fr!="Todos" and "Regime" in df_f2.columns: df_f2=df_f2[df_f2["Regime"]==fr]

        if "PTAX_Tela" in df_f2.columns:
            df_f2["PTAX_Tela"] = pd.to_numeric(df_f2["PTAX_Tela"], errors="coerce")
        
        # Sanitiza colunas com tipos mistos (float + str) para evitar erro Arrow no Streamlit
        _cols_str = ["PTAX_Bacen","PTAX_Tela","DXY","EWZ","VIX","SaldoAgressao","LiquidezCompra","LiquidezVenda",
                     "OrdensEscondidas","StatusFluxo","ConfVisual","Noticias","Diag","Motivo",
                     "TopCompradores","TopVendedores","MaiorOfertanteCompra","MaiorOfertanteVenda",
                     "EstrategiaEspecialNome","EngineMotivo","PadraoCandle","SaldoAgentes"]
        for _c in _cols_str:
            if _c in df_f2.columns:
                df_f2[_c] = df_f2[_c].astype(str)
        st.dataframe(df_f2, width='stretch', height=320)

        total=len(df_h)
        arm=(df_h["StatusGatilho"]=="ARMADO").sum() if "StatusGatilho" in df_h.columns else 0
        blo=(df_h["StatusGatilho"]=="BLOQUEADO").sum() if "StatusGatilho" in df_h.columns else 0
        esp=(df_h["StatusGatilho"]=="ESPERA").sum() if "StatusGatilho" in df_h.columns else 0

        cols_sum = st.columns(7)
        for i,(lbl,val,cor) in enumerate([
            ("Total",total,"blue"),("Armados",arm,"green"),("Bloqueados",blo,"red"),("Espera",esp,"gold"),
            ("% Arm.",f"{arm/total*100:.1f}%" if total else "0%","green"),
            ("% Blo.",f"{blo/total*100:.1f}%" if total else "0%","red"),
            ("% Esp.",f"{esp/total*100:.1f}%" if total else "0%","gold"),
        ]):
            cols_sum[i].markdown(f'<div class="metric-card"><div class="label">{lbl}</div><div class="value {cor}">{val}</div></div>', unsafe_allow_html=True)

        if "PctAcerto" in df_h.columns:
            pa=pd.to_numeric(df_h["PctAcerto"],errors="coerce").fillna(0).mean()
            pp=pd.to_numeric(df_h["PctPerda"],errors="coerce").fillna(0).mean()
            col_a1,col_a2=st.columns(2)
            col_a1.markdown(f'<div class="metric-card"><div class="label">% Médio Acerto</div><div class="value green">{pa:.1f}%</div></div>', unsafe_allow_html=True)
            col_a2.markdown(f'<div class="metric-card"><div class="label">% Médio Perda</div><div class="value red">{pp:.1f}%</div></div>', unsafe_allow_html=True)

        # === Painel de acurácia de direção ===
        if "DirecaoCorreta" in df_h.columns and "Tipo" in df_h.columns:
            df_dir = df_h[df_h["DirecaoCorreta"].isin(["sim","nao"])]
            if not df_dir.empty:
                st.markdown('<div class="section-title">🎯 Acurácia de Direção (Compra vs Venda)</div>', unsafe_allow_html=True)
                def acc(sub):
                    if len(sub)==0: return "N/A","gold"
                    s=(sub["DirecaoCorreta"]=="sim").sum()
                    p=s/len(sub)*100
                    return f"{s}/{len(sub)} ({p:.0f}%)", "green" if p>=50 else "red"
                cp,cc = acc(df_dir[df_dir["Tipo"]=="COMPRA"])
                vp,vc = acc(df_dir[df_dir["Tipo"]=="VENDA"])
                gp,gc = acc(df_dir)
                ca1,ca2,ca3=st.columns(3)
                ca1.markdown(f'<div class="metric-card"><div class="label">COMPRA — direção certa</div><div class="value {cc}">{cp}</div></div>',unsafe_allow_html=True)
                ca2.markdown(f'<div class="metric-card"><div class="label">VENDA — direção certa</div><div class="value {vc}">{vp}</div></div>',unsafe_allow_html=True)
                ca3.markdown(f'<div class="metric-card"><div class="label">Geral — direção certa</div><div class="value {gc}">{gp}</div></div>',unsafe_allow_html=True)
                st.caption("Direção correta = movimento foi a favor do gatilho (independente de atingir o alvo de pontos)")
    else:
        st.info("Nenhum gatilho registrado ainda.")

    if st.button("🗑️ Limpar Histórico"):
        st.session_state.historico_trades = []
        if os.path.exists(HISTORICO_CSV):
            try: os.remove(HISTORICO_CSV)
            except Exception: pass
        st.rerun()

    with st.expander("🔗 Fontes de dados externas"):
        for n,u in FONTES_EXTERNAS.items():
            st.markdown(f"- [{n}]({u})")

    if st.button("🪟 Listar janelas visíveis"):
        js = listar_janelas_visiveis()
        for j in js: st.write("-", j)
        if not js: st.warning("Nenhuma janela encontrada.")

    if st.button("🔍 Testar captura SuperDom + T&T"):
        c1, c2 = st.columns(2)
        with c1:
            img_sd_test, msg_sd_test = capturar_SuperDom()
            if img_sd_test: st.success(msg_sd_test); st.image(img_sd_test, width=380)
            else: st.warning(msg_sd_test)
        with c2:
            img_tt_test, msg_tt_test = capturar_times_trades()
            if img_tt_test: st.success(msg_tt_test); st.image(img_tt_test, width=380)
            else: st.warning(msg_tt_test)


# ============================================================
# ABA 2 — SINAL MINI DOLAR 9H
# ============================================================
with aba2:
    st.markdown('<div class="section-title">📈 Sinal Mini Dólar — Preparação para Abertura 9h</div>', unsafe_allow_html=True)
    st.caption("Análise macro e viés do dia anterior para orientar a direção no início do pregão.")

    if st.button("🔄 Atualizar Sinal 9h"):
        st.session_state.sinal_9h = gerar_sinal_abertura()

    if not st.session_state.sinal_9h:
        st.session_state.sinal_9h = gerar_sinal_abertura()

    sinal = st.session_state.sinal_9h
    direcao = sinal["direcao"]
    emoji_dir = sinal["emoji"]

    cor_dir = "#00e676" if "COMPRA" in direcao else ("#ff5252" if "VENDA" in direcao else "#ffd740")

    st.markdown(f"""
<div class="sinal-9h">
<h3>{emoji_dir} Direção para abertura: {direcao}</h3>
<p style="color:#8892a4;font-size:13px;margin:0">
Baseado em DXY, EWZ, VIX e viés do fechamento anterior. Confirme com a tela do Profit ao vivo.
</p>
</div>
""", unsafe_allow_html=True)

    st.markdown("**Fatores considerados:**")
    for emoji, descricao, tipo in sinal["sinais"]:
        cor = "limiar-ok" if tipo=="compra" else ("limiar-ruim" if tipo=="venda" else "limiar-medio")
        st.markdown(f'<div style="padding:6px 0;">{emoji} <span class="{cor}">{descricao}</span></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Dados usados:**")
    col_s1,col_s2,col_s3,col_s4 = st.columns(4)
    col_s1.markdown(f'<div class="metric-card"><div class="label">DXY</div><div class="value blue">{sinal["dxy"]}</div></div>', unsafe_allow_html=True)
    col_s2.markdown(f'<div class="metric-card"><div class="label">EWZ</div><div class="value blue">{sinal["ewz"]}</div></div>', unsafe_allow_html=True)
    col_s3.markdown(f'<div class="metric-card"><div class="label">VIX</div><div class="value blue">{sinal["vix"]}</div></div>', unsafe_allow_html=True)
    col_s4.markdown(f'<div class="metric-card"><div class="label">Viés anterior</div><div class="value gold">{sinal["vies"].upper()}</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
**Como usar este sinal:**

- 🟢 **COMPRA** → buscar setup comprador nos primeiros candles, preferencialmente em pullback para VWAP ou MM9.
- 🔴 **VENDA** → buscar setup vendedor, preferencialmente em rejeição de resistência ou perda da VWAP.
- 🟡 **INDEFINIDO** → aguardar os primeiros 2-3 candles para identificar a direção do dia antes de operar.

**Importante:** este sinal é um filtro de viés, não um gatilho automático. O gatilho acontece na Aba Radar Institucional com base na tela do Profit.
""")


# ============================================================
# ABA 3 — CALENDARIO + NOTICIAS
# ============================================================
with aba3:
    st.markdown('<div class="section-title">📅 Calendário Econômico + Notícias</div>', unsafe_allow_html=True)

    mac3 = ler_dados_macro()
    st.markdown("**Últimas notícias automáticas:**")
    noticias_txt = mac3.get("noticias","Noticias indisponiveis.")
    for linha in noticias_txt.split("\n"):
        if linha.strip():
            st.markdown(f"- {linha.strip()}")

    st.markdown("---")
    st.markdown("**Calendários econômicos (abre em nova aba):**")
    col_cal1, col_cal2, col_cal3 = st.columns(3)
    with col_cal1:
        st.markdown("🗓️ [TradingView](https://br.tradingview.com/economic-calendar/)")
        st.markdown("🗓️ [Trading Economics](https://pt.tradingeconomics.com/calendar)")
    with col_cal2:
        st.markdown("🗓️ [MQL5](https://www.mql5.com/pt/economic-calendar)")
        st.markdown("📰 [Notícias TradingView](https://br.tradingview.com/news/economic-category/all/)")
    with col_cal3:
        st.markdown("📰 [Trading Economics Stream](https://pt.tradingeconomics.com/stream)")
        st.markdown("💱 [Moedas](https://pt.tradingeconomics.com/currencies)")

    st.markdown("---")
    st.markdown("**Eventos importantes para o WDO:**")
    st.markdown("""
| Evento | Impacto esperado no WDO |
|---|---|
| **FOMC / Fed** | Alta volatilidade. Decisão hawkish = dólar sobe. |
| **NFP (Payroll EUA)** | Emprego forte = dólar sobe. Fraco = dólar cai. |
| **CPI EUA** | Inflação alta = dólar sobe (Fed mais duro). |
| **Selic / Copom Brasil** | Alta na Selic = real se fortalece = dólar cai. |
| **PTAX final (dias 1, 2, 3)** | Formação da taxa oficial. Alta volatilidade perto de 13h. |
| **Vencimento de contratos** | Movimento técnico de ajuste. |
| **PIB Brasil / EUA** | Dado forte do Brasil = pressão baixista no dólar. |
""")

    st.markdown("---")
    if st.button("🔄 Atualizar notícias"):
        with st.spinner("Buscando notícias..."):
            coletar_dados_macro()
        st.rerun()

st.markdown(f'<div style="text-align:center;color:#2d3561;font-size:12px;margin-top:20px;">AutoPro Radar Institucional — Ciclo #{count} — {datetime.now().strftime("%H:%M:%S")}</div>', unsafe_allow_html=True)

# ============================================================
# ABA 4 — DECISAO RAPIDA
# Uma tela, uma resposta: comprar, vender ou esperar; as faixas
# do dia; a confianca; e um botao para analisar.
# ============================================================
CSS_DECISAO_RAPIDA = """
<style>
  .dr-wrap { max-width: 900px; margin: 0 auto; }
  .dr-card { border-radius: 22px; padding: 34px 30px; margin: 6px 0 18px 0;
             border: 2px solid #232a45; position: relative; overflow: hidden;
             background: linear-gradient(150deg, #141a2b 0%, #0c1018 100%);
             box-shadow: 0 18px 48px rgba(0,0,0,.55); }
  .dr-card::after { content:""; position:absolute; inset:0; pointer-events:none;
                    background: radial-gradient(circle at 82% 12%, rgba(255,255,255,.05), transparent 55%); }
  .dr-card.compra  { border-color:#00e676; box-shadow:0 18px 48px rgba(0,230,118,.16); }
  .dr-card.venda   { border-color:#ff5252; box-shadow:0 18px 48px rgba(255,82,82,.16); }
  .dr-card.espera  { border-color:#ffd740; box-shadow:0 18px 48px rgba(255,215,64,.14); }
  .dr-eyebrow { font-size:11px; letter-spacing:3px; text-transform:uppercase;
                color:#7d879b; font-weight:700; margin-bottom:10px; }
  .dr-acao { font-size:56px; font-weight:900; letter-spacing:-1px; line-height:1;
             margin:0 0 6px 0; }
  .dr-acao.compra { color:#00e676; } .dr-acao.venda { color:#ff5252; }
  .dr-acao.espera { color:#ffd740; }
  .dr-sub { font-size:15px; color:#aab4c6; line-height:1.6; margin-top:12px; max-width:640px; }
  .dr-preco { font-size:15px; color:#e8ecf3; font-weight:600; margin-top:16px; }
  .dr-preco span { color:#7d879b; font-weight:500; }

  /* ---- medidor de confianca ---- */
  .dr-conf-box { margin-top:24px; }
  .dr-conf-top { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; }
  .dr-conf-lab { font-size:11px; letter-spacing:2px; text-transform:uppercase; color:#7d879b; font-weight:700; }
  .dr-conf-val { font-size:32px; font-weight:900; }
  .dr-bar { height:12px; border-radius:99px; background:#1b2133; overflow:hidden; }
  .dr-bar span { display:block; height:100%; border-radius:99px; transition:width .5s ease; }

  /* ---- faixas ---- */
  .dr-faixas { margin-top:6px; }
  .dr-faixa { display:grid; grid-template-columns:16px 116px 1fr auto; gap:14px;
              align-items:center; padding:15px 18px; border-radius:14px; margin-bottom:10px;
              background:#12172642; border:1px solid #1f273f; }
  .dr-faixa.ativa { border-width:2px; background:#161d3080; }
  .dr-faixa.verde.ativa    { border-color:#00e676; }
  .dr-faixa.amarela.ativa  { border-color:#ffd740; }
  .dr-faixa.vermelha.ativa { border-color:#ff5252; }
  .dr-dot { width:14px; height:14px; border-radius:50%; }
  .dr-dot.verde{background:#00e676;} .dr-dot.amarela{background:#ffd740;}
  .dr-dot.vermelha{background:#ff5252;}
  .dr-faixa-nome { font-size:13px; font-weight:800; letter-spacing:.6px; text-transform:uppercase; }
  .dr-faixa-nome.verde{color:#00e676;} .dr-faixa-nome.amarela{color:#ffd740;}
  .dr-faixa-nome.vermelha{color:#ff5252;}
  .dr-faixa-val { font-size:17px; font-weight:700; color:#e8ecf3; font-variant-numeric:tabular-nums; }
  .dr-faixa-tag { font-size:10px; letter-spacing:1.4px; text-transform:uppercase;
                  color:#8892a4; font-weight:700; }
  .dr-faixa.ativa .dr-faixa-tag { color:#e8ecf3; }
  .dr-sec { font-size:11px; letter-spacing:2.5px; text-transform:uppercase; color:#7d879b;
            font-weight:700; margin:26px 0 12px 0; }
  .dr-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:4px; }
  .dr-chip { font-size:12px; padding:7px 14px; border-radius:99px; font-weight:600;
             background:#161b2b; color:#aab4c6; border:1px solid #232a45; }
  .dr-chip.ok  { color:#00e676; border-color:#00e67655; background:#04240f66; }
  .dr-chip.bad { color:#ff5252; border-color:#ff525255; background:#2a070766; }
  .dr-foot { font-size:12px; color:#6f7a90; margin-top:22px; text-align:center; }
</style>
"""


def _dr_cor_confianca(v):
    if v >= 70:
        return "#00e676", "linear-gradient(90deg,#00b85c,#00e676)"
    if v >= 45:
        return "#ffd740", "linear-gradient(90deg,#c9a300,#ffd740)"
    return "#ff5252", "linear-gradient(90deg,#c62828,#ff5252)"


with aba4:
    st.markdown(CSS_DECISAO_RAPIDA, unsafe_allow_html=True)
    st.markdown('<div class="dr-wrap">', unsafe_allow_html=True)

    _ctx_dr = st.session_state.get("ultimo_contexto") or {}
    _dt_dr = st.session_state.get("ultimos_dados_tela") or {}
    # Sem contexto guardado (app recem-aberto), reclassifica a ultima leitura
    # em vez de mostrar a tela vazia.
    if not _ctx_dr and _dt_dr:
        try:
            _ig_dr = (st.session_state.modo_replay
                      and not st.session_state.usar_macro_no_replay)
            _ctx_dr = classificar_contexto(
                _dt_dr, ler_fechamento_anterior() if not _ig_dr else None, _ig_dr) or {}
        except Exception:
            _ctx_dr = {}
    _preco_dr = num(_dt_dr.get("preco_atual", 0))

    _sug_dr = str(_ctx_dr.get("sugestao_acao", "")).upper()
    _conv_dr = int(num(_ctx_dr.get("conviccao_ponderada", 0)))
    _exec_dr = str(_ctx_dr.get("execucao_liberada", "nao")).lower() == "sim"
    _motivo_dr = str(_ctx_dr.get("motivo_nao_executavel", ""))

    if "COMPRA" in _sug_dr and _exec_dr:
        _classe, _acao_txt = "compra", "COMPRAR"
    elif "VENDA" in _sug_dr and _exec_dr:
        _classe, _acao_txt = "venda", "VENDER"
    elif "COMPRA" in _sug_dr:
        _classe, _acao_txt = "espera", "AGUARDAR COMPRA"
    elif "VENDA" in _sug_dr:
        _classe, _acao_txt = "espera", "AGUARDAR VENDA"
    elif _sug_dr:
        _classe, _acao_txt = "espera", "NÃO OPERAR"
    else:
        _classe, _acao_txt = "espera", "SEM LEITURA"

    _txt_dr = str(_ctx_dr.get("sugestao_texto", "")) or \
        "Rode a análise para gerar a primeira leitura do pregão."
    _cor_conf, _grad_conf = _dr_cor_confianca(_conv_dr)

    _linha_preco = ""
    if _preco_dr > 0:
        _hr_dr = str(_dt_dr.get("hora_replay") or datetime.now().strftime("%H:%M"))
        _linha_preco = (f'<div class="dr-preco">{_dt_dr.get("ativo", "WDO")} '
                        f'<b>{_preco_dr:.2f}</b> <span>· leitura de {_hr_dr}</span></div>')

    st.markdown(f"""
<div class="dr-card {_classe}">
  <div class="dr-eyebrow">Decisão do robô</div>
  <div class="dr-acao {_classe}">{_acao_txt}</div>
  <div class="dr-sub">{_txt_dr}</div>
  {_linha_preco}
  <div class="dr-conf-box">
    <div class="dr-conf-top">
      <span class="dr-conf-lab">Confiança</span>
      <span class="dr-conf-val" style="color:{_cor_conf}">{_conv_dr}%</span>
    </div>
    <div class="dr-bar"><span style="width:{max(3, min(100, _conv_dr))}%;background:{_grad_conf}"></span></div>
  </div>
</div>""", unsafe_allow_html=True)

    # ---------------- FAIXAS DE OPERACAO ----------------
    st.markdown('<div class="dr-sec">Faixas de operação — referência do pregão anterior</div>',
                unsafe_allow_html=True)
    try:
        _fx_dr = calcular_faixas_operacionais(ler_fechamento_anterior(), _dt_dr)
    except Exception:
        _fx_dr = {"valido": False}

    if _fx_dr.get("valido"):
        _atual = str(_fx_dr.get("faixa_atual", ""))
        _linhas_fx = ""
        for _nome, _lab, _tag in (("verde", "Compra", "Zona de defesa compradora"),
                                  ("amarela", "Neutra", "Aguardar definição"),
                                  ("vermelha", "Venda", "Zona de oferta vendedora")):
            _ini, _fim = _fx_dr.get(_nome, (0.0, 0.0))
            _cls = f"dr-faixa {_nome}" + (" ativa" if _atual == _nome else "")
            _tg = "◀ PREÇO AQUI" if _atual == _nome else _tag
            _linhas_fx += (
                f'<div class="{_cls}"><div class="dr-dot {_nome}"></div>'
                f'<div class="dr-faixa-nome {_nome}">{_lab}</div>'
                f'<div class="dr-faixa-val">{_ini:.2f} — {_fim:.2f}</div>'
                f'<div class="dr-faixa-tag">{_tg}</div></div>')
        st.markdown(f'<div class="dr-faixas">{_linhas_fx}</div>', unsafe_allow_html=True)
        _dref = str(_fx_dr.get("data_referencia", ""))
        try:
            _dref_fmt = datetime.strptime(_dref, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            _dref_fmt = _dref or "—"
        _aj_ant_txt = (f"{_fx_dr.get('ajuste_ant', 0):.2f}"
                       if num(_fx_dr.get("ajuste_ant", 0)) > 0 else "não capturado")
        _fonte_dr = str(_fx_dr.get("fonte_referencia", ""))
        _rot_fonte = {
            "tela_pregao_anterior": "lido do gráfico",
            "tela_pregao_anterior (memoria)": "lido do gráfico",
            "range_acumulado": "pregão anterior",
            "historico": "pregão anterior (histórico)",
            "fechamento": "fechamento anterior",
            "pregao_anterior_historico": "pregão anterior (histórico)",
            "pregao_anterior_registrado": "pregão anterior registrado",
            "range_do_dia_corrente": "range do dia corrente",
            "range_do_dia_corrente (escala trocada)": "range do dia corrente",
            "estimada_pela_leitura_atual": "estimativa pela leitura atual",
        }.get(_fonte_dr, _fonte_dr or "—")
        if _fonte_dr.startswith("referencia_antiga_"):
            _rot_fonte = f"referência antiga ({_fonte_dr.split('_')[-1]} do pregão anterior)"
        st.caption(f"Referência **{_dref_fmt}** ({_rot_fonte}) · "
                   f"máxima {_fx_dr.get('maxima_ant', 0):.2f} · "
                   f"mínima {_fx_dr.get('minima_ant', 0):.2f} · "
                   f"ajuste {_aj_ant_txt} · "
                   f"amplitude {_fx_dr.get('amplitude_ant', 0):.1f} pts")
        # Confere se a referencia e MESMO o dia util anterior ao pregao lido.
        try:
            _esperado_dr = dia_util_anterior(
                _data_referencia_leitura(st.session_state.get("ultimos_dados_tela")))
            if _dref and _dref != _esperado_dr:
                _esp_fmt = datetime.strptime(_esperado_dr, "%Y-%m-%d").strftime("%d/%m/%Y")
                st.warning(
                    f"As faixas estão em **{_dref_fmt}**, mas o pregão anterior é "
                    f"**{_esp_fmt}**. Deixe as linhas de máxima, mínima e o "
                    f"*Prior Cote Ajuste* visíveis no gráfico e use "
                    f"**Ler pregão anterior do gráfico** abaixo.")
        except Exception:
            pass
    if not _fx_dr.get("valido"):
        _dref2 = str(_fx_dr.get("data_referencia", "")) or "—"
        st.caption(f"Sem dados do pregão de {_dref2}. As faixas aparecem depois "
                   f"da primeira sessão registrada nessa data.")
    else:
        st.info("As faixas aparecem após o primeiro fechamento registrado.")

    # ---------------- O QUE PESA AGORA ----------------
    _chips = []
    if _ctx_dr:
        _sc = int(num(_ctx_dr.get("score", 0)))
        _smin = int(num(_ctx_dr.get("score_minimo_usado", 0)))
        _chips.append((f"Score {_sc}/{_smin}", _sc >= _smin))
        _chips.append((f"Gatilho {_ctx_dr.get('status_gatilho', 'ESPERA')}",
                       str(_ctx_dr.get("status_gatilho", "")) == "ARMADO"))
        _chips.append((f"Regime {_ctx_dr.get('regime', '—')}", True))
        if _ctx_dr.get("bollinger_estado"):
            _chips.append((f"Bollinger {_ctx_dr['bollinger_estado']}", True))
        if num(_ctx_dr.get("ifr", 0)) > 0:
            _chips.append((f"IFR {num(_ctx_dr['ifr']):.0f}", True))
        if _ctx_dr.get("macro_vies") and _ctx_dr.get("macro_vies") != "neutro":
            _chips.append((f"Macro {_ctx_dr['macro_vies']}", True))
    if _chips:
        st.markdown('<div class="dr-sec">O que pesa nesta leitura</div>', unsafe_allow_html=True)
        _html_chips = "".join(
            f'<span class="dr-chip {"ok" if _o else "bad"}">{_t}</span>' for _t, _o in _chips)
        st.markdown(f'<div class="dr-chips">{_html_chips}</div>', unsafe_allow_html=True)

    if not _exec_dr and _motivo_dr:
        st.markdown('<div class="dr-sec">Por que não enviar ordem</div>', unsafe_allow_html=True)
        st.warning(_motivo_dr)

    # ---------------- CICLO AUTOMATICO NESTA ABA ----------------
    # O Streamlit volta para a primeira aba a cada rerun, e o ciclo vivia no
    # bloco da aba 1: parado nesta tela, a leitura parecia congelada. Aqui a
    # verificacao e propria. Se a aba 1 ja rodou neste rerun, o tempo decorrido
    # zera e este bloco nao dispara de novo.
    _int_dr = intervalo_analise_atual()
    _dec_dr = time.time() - num(st.session_state.get("ultimo_ciclo_analise", 0))
    _falta_dr = max(0, int(_int_dr - _dec_dr))
    _jan_ativa_dr = bool((st.session_state.get("estado_janela") or {}).get("dentro", True))

    # O ciclo global (antes das abas) ja cuidou da leitura automatica: aqui
    # apenas exibimos o estado, sem disparar uma segunda analise.

    _ult_leitura_dr = ""
    try:
        _ts_dr = num(st.session_state.get("ultimo_ciclo_analise", 0))
        if _ts_dr > 0:
            _ult_leitura_dr = datetime.fromtimestamp(_ts_dr).strftime("%H:%M:%S")
    except Exception:
        pass

    _c1_dr, _c2_dr, _c3_dr = st.columns(3)
    _c1_dr.metric("Última leitura", _ult_leitura_dr or "—")
    _c2_dr.metric("Próxima em", f"{_falta_dr // 60}:{_falta_dr % 60:02d}")
    _c3_dr.metric("Automático",
                  "ligado" if st.session_state.get("analise_automatica") else "desligado")

    # ---------------- LER O PREGAO ANTERIOR DO GRAFICO ----------------
    _cb1_dr, _cb2_dr = st.columns([1, 1])
    if _cb2_dr.button("📐  Ler pregão anterior do gráfico",
                      use_container_width=True, key="btn_ler_pregao_ant"):
        if not CHAVE_OPENROUTER:
            st.error("Defina a variável de ambiente OPENROUTER_API_KEY antes de executar.")
        else:
            with st.spinner("Lendo máxima, mínima e ajuste do pregão anterior..."):
                try:
                    _img_pa, _msg_pa = capturar_janela()
                    _lido_pa = extrair_dados_tela(_img_pa, st.session_state.modo_replay) if _img_pa else None
                    if not _lido_pa:
                        st.error(f"Não consegui ler o gráfico. {_msg_pa or ''}")
                    else:
                        _mxp = num(_lido_pa.get("maxima_anterior", 0))
                        _mnp = num(_lido_pa.get("minima_anterior", 0))
                        _ajp = num(_lido_pa.get("ajuste_anterior", 0))
                        _dtp = str(_lido_pa.get("data_pregao_anterior", "") or "")[:10]
                        _base_pa = st.session_state.get("ultimos_dados_tela") or _lido_pa
                        _dia_pa = _data_referencia_leitura(_base_pa)
                        if not re.match(r"^\d{4}-\d{2}-\d{2}$", _dtp):
                            _dtp = dia_util_anterior(_dia_pa)
                        if _mxp > _mnp > 0:
                            _at_pa = ativo_canonico(_base_pa.get("ativo", "")) or "ATIVO"
                            _cc = st.session_state.get("ref_pregao_anterior_tela")
                            if not isinstance(_cc, dict):
                                _cc = {}
                            _cc[f"{_at_pa}::{_dia_pa}"] = {
                                "maxima": round(_mxp, 2), "minima": round(_mnp, 2),
                                "ajuste": round(_ajp, 2), "vwap": 0.0,
                                "data": _dtp, "fonte": "tela_pregao_anterior"}
                            st.session_state["ref_pregao_anterior_tela"] = _cc
                            invalidar_faixas_travadas()
                            st.success(
                                f"Pregão anterior lido: {_dtp} · máxima {_mxp:.2f} · "
                                f"mínima {_mnp:.2f} · ajuste {_ajp:.2f}")
                            st.rerun()
                        else:
                            st.warning(
                                "Não localizei máxima e mínima do pregão anterior no "
                                "gráfico. Deixe as linhas de Máximo/Mínimo e o "
                                "Prior Cote Ajuste visíveis e tente de novo.")
                except Exception as _e_pa:
                    st.error(f"Falha ao ler o pregão anterior: {_e_pa}")

    # ---------------- BOTAO DE ANALISE ----------------
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔍  ANALISAR AGORA", use_container_width=True, type="primary",
                 key="btn_analise_decisao_rapida"):
        if not CHAVE_OPENROUTER:
            st.error("Defina a variável de ambiente OPENROUTER_API_KEY antes de executar.")
        else:
            with st.spinner("Lendo a tela e consolidando a decisão..."):
                try:
                    executar_analise()
                    st.session_state.ultimo_ciclo_analise = time.time()
                except Exception as _e:
                    st.error(f"Não foi possível concluir a análise: {_e}")
            st.rerun()

    _jan_dr = st.session_state.get("estado_janela") or {}
    st.markdown(
        f'<div class="dr-foot">{_jan_dr.get("resumo", "")} · '
        f'análise automática a cada {INTERVALO_ANALISE_SEGUNDOS // 60} min</div>',
        unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
