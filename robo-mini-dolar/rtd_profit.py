"""Fonte de dados alternativa a captura de tela: le o Profit direto pelo
RTD (Real-Time Data) que a Nelogica ja expoe via COM — o mesmo protocolo
que o Excel usa em formulas tipo ``=RTD("profitdll.rtd";;"WDOV26_F_0";"ULT")``.
Nao depende de janela visivel nem de IA de visao: enquanto o Profit
estiver aberto e logado, os campos chegam certos (preco, abertura,
maxima, minima, ajuste do pregao anterior, volume acumulado do dia).

Este modulo e independente do Streamlit e do resto do app — so usa
pywin32 (``win32com.client``/``pythoncom``), e mesmo essas dependencias
so sao importadas dentro de ``LeitorRTD.conectar()``, para o modulo
continuar importavel (e testavel) em qualquer SO.

Peca central para o app (``robo_mini_dolar.py``):
    - ``FonteDadosRTD(ticker).conectar()`` uma vez por sessao;
    - a cada ciclo, ``ler_dados_tela()`` devolve um dict no MESMO formato
      que ``extrair_dados_tela()`` (captura de tela + IA) ja devolve, e
      ``hist_candles()`` no MESMO formato de ``st.session_state["hist_candles"]``
      — os dois plugam direto nos consumidores existentes sem mudar nada
      neles.
"""
from dataclasses import dataclass
from datetime import datetime


# =============================================================================
# CONVERSAO NUMERICA — o RTD devolve string, float, ou uma das mensagens de
# erro documentadas pela Nelogica quando o dado nao esta disponivel (Profit
# fechado, ativo sem book, RTD desligado etc.). Nenhuma delas pode virar um
# preco — precisa sempre degradar para 0.0, nunca lancar excecao.
# =============================================================================
_MENSAGENS_ERRO_RTD = {
    "#N/D", "RTD Desativado", "Ferramenta Invalida",
    "Atributo Invalido", "A janela foi fechada",
}


def _num(v, default=0.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        try:
            if isinstance(v, float) and v != v:  # NaN nunca e igual a si mesmo
                return default
        except Exception:
            pass
        return float(v)
    s = str(v).strip()
    if not s or s in _MENSAGENS_ERRO_RTD:
        return default
    s = s.replace(" ", "")
    # Formato brasileiro: "5.120,50" (milhar+decimal) ou so "5120,50" (decimal).
    if "," in s:
        s = s.replace(".", "").replace(",", ".") if "." in s else s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return default


# =============================================================================
# AGREGADOR DE CANDLES — o RTD entrega ticks (preco a cada mudanca), nao
# candles prontos. Agrega no timeframe operacional do app (5 ou 10 min,
# igual ao resto do sistema) para alimentar MM9/20/50/200, VWAP, ATR e
# o gatilho de rompimento (gatilho_rompimento_candle ja espera esse
# formato em st.session_state["hist_candles"]).
# =============================================================================
@dataclass
class Candle:
    inicio: datetime
    abertura: float
    maxima: float
    minima: float
    fechamento: float
    volume: float = 0.0
    segundos: float = 0.0


class AgregadorCandles:
    def __init__(self, timeframe_min=5):
        self.timeframe_min = max(1, int(timeframe_min))
        self.candles = []  # mais ANTIGO primeiro; candles[-1] = candle em formacao
        self._ultimo_volume_acumulado = None

    def _bucket(self, quando):
        m = (quando.minute // self.timeframe_min) * self.timeframe_min
        return quando.replace(minute=m, second=0, microsecond=0)

    def _delta_volume(self, volume_acumulado):
        """RTD entrega o volume ACUMULADO DO DIA, nao o volume do candle —
        o candle quer so o incremento desde a ultima leitura. Na primeira
        leitura da sessao (sem baseline ainda) o acumulado inteiro vira o
        incremento inicial. Se o acumulado CAIR (virada de dia/pregao,
        contador zerado) o delta ficaria negativo — nesse caso descarta o
        incremento (0) em vez de subtrair volume do candle."""
        if volume_acumulado is None:
            return 0.0
        vol = _num(volume_acumulado)
        if self._ultimo_volume_acumulado is None:
            delta = vol
        else:
            delta = vol - self._ultimo_volume_acumulado
        self._ultimo_volume_acumulado = vol
        return max(0.0, delta)

    def registrar(self, preco, volume_acumulado=None, quando=None):
        """Registra um tick de preco. Preco invalido (<=0) e IGNORADO —
        nao abre candle nem consome o baseline de volume."""
        preco = _num(preco)
        if preco <= 0:
            return
        quando = quando or datetime.now()
        delta_vol = self._delta_volume(volume_acumulado)
        bucket = self._bucket(quando)

        if self.candles and self.candles[-1].inicio == bucket:
            c = self.candles[-1]
            c.maxima = max(c.maxima, preco)
            c.minima = min(c.minima, preco)
            c.fechamento = preco
            c.volume += delta_vol
            c.segundos = (quando - bucket).total_seconds()
        else:
            self.candles.append(Candle(
                inicio=bucket, abertura=preco, maxima=preco, minima=preco,
                fechamento=preco, volume=delta_vol,
                segundos=(quando - bucket).total_seconds(),
            ))

    def media_movel(self, n):
        """0.0 quando nao ha os N candles pedidos — nunca um valor
        inventado a partir de uma amostra menor (era exatamente o bug de
        MM200 aparecer com 1 candle de historico)."""
        if n <= 0 or len(self.candles) < n:
            return 0.0
        fechamentos = [c.fechamento for c in self.candles[-n:]]
        return round(sum(fechamentos) / n, 2)

    def vwap_sessao(self):
        vol_total = sum(c.volume for c in self.candles)
        if vol_total <= 0:
            return 0.0
        soma = sum(((c.maxima + c.minima + c.fechamento) / 3.0) * c.volume
                    for c in self.candles)
        return round(soma / vol_total, 2)

    def atr(self, periodo=14):
        if len(self.candles) < 2:
            return 0.0
        trs = []
        for i in range(1, len(self.candles)):
            atual, anterior = self.candles[i], self.candles[i - 1]
            trs.append(max(
                atual.maxima - atual.minima,
                abs(atual.maxima - anterior.fechamento),
                abs(atual.minima - anterior.fechamento),
            ))
        amostra = trs[-periodo:] if len(trs) >= periodo else trs
        return round(sum(amostra) / len(amostra), 3) if amostra else 0.0

    def para_hist_candles(self):
        """Mesmo formato/ordem de st.session_state['hist_candles'] no resto
        do app: mais RECENTE no indice 0."""
        return [
            {"abertura": c.abertura, "maxima": c.maxima, "minima": c.minima,
             "fechamento": c.fechamento, "volume": c.volume, "segundos": c.segundos}
            for c in reversed(self.candles)
        ]

    def semear_historico(self, hist_candles):
        """Preenche o aggregador com candles ja persistidos pelo app (mesmo
        formato de para_hist_candles/st.session_state['hist_candles'],
        mais recente no indice 0) — usado ao trocar para a fonte RTD no
        meio do dia, para as medias longas (MM50/MM200) nao terem que
        esperar o dia inteiro de novo. Candle sem OHLC valido e descartado.
        Devolve quantos candles foram aceitos."""
        aceitos = 0
        # hist_candles vem mais-recente-primeiro; self.candles e
        # mais-antigo-primeiro — inverte para preservar a ordem cronologica.
        for c in reversed(list(hist_candles or [])):
            ab, mx, mn, fc = (_num(c.get("abertura", 0)), _num(c.get("maxima", 0)),
                              _num(c.get("minima", 0)), _num(c.get("fechamento", 0)))
            if mx <= 0 or mn <= 0 or fc <= 0:
                continue
            # inicio = datetime.min para todo candle semeado: bem no passado,
            # nunca colide com o bucket de um tick real (datetime.now()).
            self.candles.append(Candle(
                inicio=datetime.min, abertura=ab, maxima=mx, minima=mn,
                fechamento=fc, volume=_num(c.get("volume", 0)),
                segundos=_num(c.get("segundos", 0)),
            ))
            aceitos += 1
        return aceitos


# =============================================================================
# LEITOR RTD — conexao COM de baixo nivel com o servidor RTD do Profit.
# =============================================================================
class LeitorRTD:
    # Campos padrao do RTD do Profit/Nelogica (documentados pela corretora):
    # ULT=ultimo negociado, ABE=abertura, MAX=maxima, MIN=minima,
    # AJA=ajuste do pregao anterior, VOL=volume financeiro acumulado do dia.
    ATRIBUTOS_PADRAO = {
        "ultimo": "ULT", "abertura": "ABE", "maxima": "MAX",
        "minima": "MIN", "ajuste_ant": "AJA", "volume": "VOL",
    }

    def __init__(self, ticker, progid="ProfitDLL.RTD"):
        self.ticker = str(ticker).strip().upper()
        # Sufixo "_F_0" = ticker de futuro, vencimento corrente — mesmo
        # formato usado nas planilhas RTD que a Nelogica distribui.
        self.ticker_rtd = f"{self.ticker}_F_0"
        self.progid = progid
        self.atributos = dict(self.ATRIBUTOS_PADRAO)
        self._servidor = None
        self._topicos = {}
        self._proximo_topico = 1
        self.conectado = False

    def conectar(self):
        """So funciona no Windows, com o Profit aberto e RTD habilitado.
        O ProgID exato do servidor varia por instalacao/corretora — ajuste
        self.progid (passado no construtor) se a conexao falhar com o
        padrao. Nunca lanca excecao: devolve (ok, motivo)."""
        try:
            import pythoncom
            import win32com.client
        except ImportError as e:
            self.conectado = False
            return False, f"pywin32 indisponivel ({e}) — so funciona no Windows."
        try:
            pythoncom.CoInitialize()
            self._servidor = win32com.client.Dispatch(self.progid)
            self._servidor.ServerStart(None)
            self._topicos = {}
            self._proximo_topico = 1
            for nome, attr in self.atributos.items():
                tid = self._proximo_topico
                self._proximo_topico += 1
                self._servidor.ConnectData(tid, [self.ticker_rtd, attr], True)
                self._topicos[tid] = nome
            self.conectado = True
            return True, ""
        except Exception as e:
            self._servidor = None
            self.conectado = False
            return False, str(e)

    def desconectar(self):
        if self._servidor is not None:
            for tid in list(self._topicos):
                try:
                    self._servidor.DisconnectData(tid)
                except Exception:
                    pass
            try:
                self._servidor.ServerTerminate()
            except Exception:
                pass
        self._servidor = None
        self._topicos = {}
        self.conectado = False

    def ler(self):
        """Le o snapshot atual dos topicos conectados. Nunca lanca
        excecao — Profit fechado ou erro de RefreshData degradam para uma
        estrutura segura (tudo 0.0 + motivo em 'erro'), nunca um numero
        inventado."""
        vazio = {"conectado": False, "ultimo": 0.0, "abertura": 0.0, "maxima": 0.0,
                 "minima": 0.0, "ajuste_ant": 0.0, "volume": 0.0,
                 "erro": "nao conectado ao RTD"}
        if not self.conectado or self._servidor is None:
            return vazio
        try:
            _count, linhas = self._servidor.RefreshData(len(self._topicos) or -1)
        except Exception as e:
            out = dict(vazio)
            out["conectado"] = True
            out["erro"] = f"RefreshData falhou: {e}"
            return out
        saida = {"conectado": True, "ultimo": 0.0, "abertura": 0.0, "maxima": 0.0,
                 "minima": 0.0, "ajuste_ant": 0.0, "volume": 0.0, "erro": ""}
        try:
            ids, vals = linhas[0], linhas[1]
            for tid_f, val in zip(ids, vals):
                nome = self._topicos.get(int(tid_f))
                if nome:
                    saida[nome] = _num(val)
        except Exception as e:
            saida["erro"] = f"leitura de RefreshData malformada: {e}"
        return saida


# =============================================================================
# FACHADA — mesmo formato de extrair_dados_tela()/hist_candles do resto do
# app, para plugar em obter_dados_mercado_externo() sem tocar em mais nada.
# =============================================================================
class FonteDadosRTD:
    def __init__(self, ticker, timeframe_min=5, progid="ProfitDLL.RTD"):
        self.leitor = LeitorRTD(ticker, progid=progid)
        self.agregador = AgregadorCandles(timeframe_min=timeframe_min)

    def conectar(self):
        return self.leitor.conectar()

    def semear_historico(self, hist_candles):
        return self.agregador.semear_historico(hist_candles)

    def ler_dados_tela(self):
        d = self.leitor.ler()
        preco = d.get("ultimo", 0.0)
        conectado = bool(d.get("conectado"))
        if conectado and preco > 0:
            self.agregador.registrar(preco, volume_acumulado=d.get("volume", 0.0))

        vwap, vwap_origem = 0.0, "indisponivel"
        if conectado:
            fonte = "rtd"
            vwap = self.agregador.vwap_sessao()
            vwap_origem = "calculado_rtd" if vwap > 0 else "indisponivel"
        else:
            fonte = "rtd_indisponivel"

        ultimo_candle = self.agregador.candles[-1] if self.agregador.candles else None
        return {
            "ativo": self.leitor.ticker,
            "preco_atual": preco,
            "abertura": d.get("abertura", 0.0),
            "maxima": d.get("maxima", 0.0),
            "minima": d.get("minima", 0.0),
            "ajuste": d.get("ajuste_ant", 0.0),
            "volume": ultimo_candle.volume if ultimo_candle else 0.0,
            "vwap": round(vwap, 2),
            "vwap_origem": vwap_origem,
            "mm9": self.agregador.media_movel(9),
            "mm20": self.agregador.media_movel(20),
            "mm50": self.agregador.media_movel(50),
            "mm200": self.agregador.media_movel(200),
            "rtd_conectado": conectado,
            "fonte_dados": fonte,
            "erro_rtd": d.get("erro", ""),
        }

    def hist_candles(self):
        return self.agregador.para_hist_candles()
