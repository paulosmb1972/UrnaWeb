"""Testes da engine de decisao — foco no bug "conviccao fabricada por
ausencia de dados", diagnosticado no replay de 12/09/2026 (leitura das
16:47:21: score 0/4, tela zerada, book em venda com forca 100, e mesmo
assim 94% de conviccao ponderada).

Rodar de dentro de robo-mini-dolar/:
    python3 -m unittest tests.test_engine -v
"""
import unittest

from tests._mock_env import carregar_engine

NS = None
FAKE_ST = None


def setUpModule():
    global NS, FAKE_ST
    NS, FAKE_ST = carregar_engine()


class TestIndicadoresDeAusencia(unittest.TestCase):
    """BUG 1 — um indicador de ausencia (sem_absorcao_contra,
    sem_rompimento_seco) so pode pontuar se a fonte dele foi lida."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.detectar = NS["_detectar_indicadores"]

    def _ctx_base(self, **over):
        base = {
            "regime": "trend_up", "momentum": "neutro", "score": 0,
            "previsao_confianca": 0, "rr": 0,
            "fluxo_valido": False, "absorcao_favoravel": False,
            "rompimento_dispara": False, "reversao_extremo": False,
            "pullback_favoravel": False, "zona_morta": False, "pos_range": -1,
            "acao_pretendida": "compra", "dist_mm9": 0,
        }
        base.update(over)
        return base

    def test_sem_absorcao_contra_nao_dispara_sem_book_lido(self):
        """Leitura das 16:47: sem book (fluxo_valido=False) — o indicador
        de ausencia de absorcao contraria NAO pode contar como evidencia."""
        dados_tela = {"preco_atual": 5124.5, "maxima": 5125.0, "minima": 5088.0,
                      "mm9": 0.0, "mm20": 0.0, "vwap": 0.0, "volume": 0,
                      "hora_replay": "16:47"}
        ctx = self._ctx_base(fluxo_valido=False, absorcao_favoravel=False)
        presentes = self.detectar(ctx, dados_tela)
        self.assertNotIn("sem_absorcao_contra", presentes)

    def test_sem_absorcao_contra_dispara_com_book_lido_e_sem_absorcao(self):
        """Controle: com o book de fato lido (fluxo_valido=True) e sem
        absorcao contraria detectada, o indicador continua valendo — a
        correcao nao pode ter desligado o caso legitimo."""
        dados_tela = {"preco_atual": 5150.0, "maxima": 5160, "minima": 5140,
                      "mm9": 5148.0, "mm20": 5145.0, "vwap": 5149.0, "volume": 500,
                      "hora_replay": "10:30"}
        ctx = self._ctx_base(fluxo_valido=True, absorcao_favoravel=False)
        presentes = self.detectar(ctx, dados_tela)
        self.assertIn("sem_absorcao_contra", presentes)

    def test_sem_rompimento_seco_nao_dispara_sem_candle_lido(self):
        """maxima/minima zerados e nenhum historico de candle: sem como
        avaliar rompimento nenhum, entao "sem rompimento seco" nao pode
        contar como sinal de entrada limpa."""
        dados_tela = {"preco_atual": 5147.0, "maxima": 0, "minima": 0,
                      "mm9": 0.0, "mm20": 0.0, "vwap": 0.0, "volume": 0,
                      "hora_replay": "03:14"}
        ctx = self._ctx_base(rompimento_dispara=False)
        FAKE_ST.session_state["hist_candles"] = []
        presentes = self.detectar(ctx, dados_tela)
        self.assertNotIn("sem_rompimento_seco", presentes)

    def test_sem_rompimento_seco_dispara_com_candle_lido(self):
        """Controle: com historico de candle de verdade (>=2 candles) e sem
        rompimento detectado, o indicador continua valendo."""
        dados_tela = {"preco_atual": 5150.0, "maxima": 5160, "minima": 5140,
                      "mm9": 5148.0, "mm20": 5145.0, "vwap": 5149.0, "volume": 500,
                      "hora_replay": "10:30"}
        ctx = self._ctx_base(rompimento_dispara=False)
        FAKE_ST.session_state["hist_candles"] = [
            {"maxima": 5155, "minima": 5142, "abertura": 5145, "fechamento": 5150,
             "volume": 100, "segundos": 200},
            {"maxima": 5150, "minima": 5138, "abertura": 5140, "fechamento": 5145,
             "volume": 90, "segundos": 300},
        ]
        presentes = self.detectar(ctx, dados_tela)
        self.assertIn("sem_rompimento_seco", presentes)


class TestLiberarTendenciaFortesemPullback(unittest.TestCase):
    """BUG 2 — o unico caminho que arma direcao sem pullback/rompimento
    confirmado nao pode liberar quando a leitura nao tem estrutura de preco
    (candle do dia + pelo menos uma media movel), mesmo com conviccao
    ponderada alta e mesmo com ou sem dado de book."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.liberar = NS["liberar_tendencia_forte_sem_pullback"]

    def _ctx_16h47(self, **over):
        # Reproduz a leitura real de 12/09 as 16:47:21: score 0/4, regime
        # trend_up, conviccao ponderada fabricada em 94%, tela sem
        # estrutura (maxima/minima/mm9/mm20 e volume zerados).
        ctx = {
            "acao_objetiva": "espera", "regime": "trend_up",
            "conviccao_ponderada": 94, "conflito": False,
            "exaustao_topo": False, "exaustao_fundo": False, "volume_ok": True,
            "lotes_vies": "", "lotes_forca": 0,
            "agressao_pct_leitura": 50.0,
            "validacao": {"consistente": True},
        }
        ctx.update(over)
        return ctx

    def _dados_tela_zerado(self):
        return {"preco_atual": 5124.5, "maxima": 0, "minima": 0,
                "mm9": 0.0, "mm20": 0.0, "vwap": 0.0, "volume": 0}

    def test_nao_libera_sem_estrutura_mesmo_com_conviccao_94_e_sem_book(self):
        ctx = self._ctx_16h47(lotes_vies="", lotes_forca=0)
        resultado = self.liberar(ctx, self._dados_tela_zerado())
        self.assertEqual(resultado.get("acao_objetiva"), "espera")
        self.assertTrue(resultado.get("liberacao_bloqueada_sem_estrutura"))

    def test_nao_libera_sem_estrutura_mesmo_com_book_apontando_a_favor(self):
        """Critério de aceite explícito: mesmo que agressão/lotes calhem de
        apontar para o mesmo lado do regime (o que já bloqueava a leitura
        real de 16:47 por coincidência — book estava em venda), a guarda
        estrutural bloqueia antes disso, por desenho, não por sorte."""
        ctx = self._ctx_16h47(lotes_vies="compra", lotes_forca=100,
                               agressao_pct_leitura=80.0)
        resultado = self.liberar(ctx, self._dados_tela_zerado())
        self.assertEqual(resultado.get("acao_objetiva"), "espera")
        self.assertTrue(resultado.get("liberacao_bloqueada_sem_estrutura"))

    def test_libera_normalmente_com_estrutura_de_preco_e_sinais_alinhados(self):
        """Controle: candle do dia e média móvel presentes, convicção alta,
        agressão e lotes alinhados com a direção do regime — a correção não
        pode ter quebrado o caminho de liberação legítimo."""
        ctx = self._ctx_16h47(lotes_vies="compra", lotes_forca=100,
                               agressao_pct_leitura=80.0)
        dados_tela = {"preco_atual": 5150.0, "maxima": 5160, "minima": 5140,
                      "mm9": 5148.0, "mm20": 5145.0, "vwap": 5149.0, "volume": 500}
        resultado = self.liberar(ctx, dados_tela)
        self.assertEqual(resultado.get("acao_objetiva"), "compra")
        self.assertNotIn("liberacao_bloqueada_sem_estrutura", resultado)


class TestVolumeProfileFallbackTPO(unittest.TestCase):
    """BUG 3 — captura de tela nunca le o campo "volume" do candle (ver
    VolumeStatus="nao_lido" no CSV do dia 15/09/2026: 27/27 leituras), entao
    todo candle guardado em hist_candles chegava com volume=0 e
    calcular_volume_profile desistia sempre, rotulando o motivo como
    "amostra insuficiente" mesmo com dezenas de candles disponiveis (ex.:
    "33/3 candles" — 33 candles para um minimo de 3, mensagem enganosa).

    Correcao: quando NENHUM candle da amostra tem volume real, o perfil usa
    peso 1 por candle (TPO — tempo no preco) em vez de devolver
    indisponivel; e o motivo do "indisponivel" (quando genuino) passa a
    ser especifico em vez de sempre "amostra insuficiente"."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.calc = NS["calcular_volume_profile"]

    def _candles(self, n=33, volume=0):
        preco = 5150.0
        candles = []
        for i in range(n):
            preco += (i % 5) - 2
            candles.append({"maxima": preco + 3, "minima": preco - 3,
                             "volume": volume, "abertura": preco, "fechamento": preco})
        return candles

    def test_amostra_grande_sem_volume_real_nao_fica_indisponivel(self):
        """Reproducao exata do caso relatado: 33 candles, todos com
        volume=0 — antes voltava sempre "indisponivel"."""
        r = self.calc(hist=self._candles(n=33, volume=0))
        self.assertTrue(r["valido"])
        self.assertTrue(r["modo_estimado"])
        self.assertGreater(r["poc"], 0)

    def test_com_volume_real_mantem_calculo_original_sem_modo_estimado(self):
        """Controle: existindo volume real em pelo menos 1 candle, o
        resultado nao pode ser sinalizado como estimado."""
        candles = self._candles(n=33, volume=0)
        for i, c in enumerate(candles):
            c["volume"] = 100 + (i * 7) % 50
        r = self.calc(hist=candles)
        self.assertTrue(r["valido"])
        self.assertFalse(r["modo_estimado"])

    def test_amostra_insuficiente_continua_indisponivel(self):
        """Poucos candles (abaixo do minimo) continua indisponivel de
        verdade — o fallback nao pode mascarar esse caso."""
        r = self.calc(hist=self._candles(n=2, volume=0))
        self.assertFalse(r["valido"])
        self.assertEqual(r["motivo"], "amostra insuficiente")


class TestViesMacroDXYSemLeituraAnterior(unittest.TestCase):
    """BUG 4 — diagnosticado no export do dia 15/09/2026: a aba Macro
    ficava com vies e "% de confianca" travados no mesmo valor por horas.
    Causa raiz: DXY vem do FRED (serie DTWEXBGS, resolucao DIARIA — nao
    muda dentro do mesmo dia). O corte de "sem leitura anterior" usava
    NIVEL ABSOLUTO (>=105 dolar forte / <=97 dolar fraco) calibrado pro
    DXY classico da ICE (90-115); o DTWEXBGS gira naturalmente em 115-130,
    entao ">=105" era quase sempre verdadeiro e o DXY votava "dolar forte"
    (+1 ponto) todo dia, o dia inteiro, travando a conta."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.vies = NS["vies_macro_consolidado"]

    def _macro_base(self, **over):
        base = {"DXY": 118.2126, "VIX": 17.10, "PTAX": 5.1490, "EWZ": 37.90,
                "macro_indisponiveis": [], "macro_indisponiveis_essenciais": []}
        base.update(over)
        return base

    def test_dxy_sem_leitura_anterior_nao_pontua_pelo_nivel_absoluto(self):
        """Reproducao do caso real: DXY em 118.21 (nivel do DTWEXBGS, nao do
        DXY classico), sem DXY_ANTERIOR — antes isso sozinho já classificava
        "dolar forte" (+1); agora fica neutro, so informativo."""
        r = self.vies(self._macro_base())
        self.assertEqual(r["pontos"], 0)
        self.assertEqual(r["vies"], "neutro")
        self.assertTrue(any("não pontua" in f for f in r["fatores"]))

    def test_dxy_estavel_no_mesmo_dia_nao_pontua(self):
        """Controle: DXY_ANTERIOR igual ao atual (mesma leitura diaria
        repetida ao longo do dia) — variacao 0%, nao pode pontuar."""
        r = self.vies(self._macro_base(DXY_ANTERIOR=118.2126))
        self.assertEqual(r["pontos"], 0)

    def test_dxy_com_variacao_real_dia_a_dia_continua_pontuando(self):
        """Controle: quando existe de fato uma leitura anterior diferente
        (dia seguinte, DXY subiu 0.30%), a correcao nao pode ter quebrado o
        caminho de pontuacao por variacao percentual."""
        r = self.vies(self._macro_base(DXY_ANTERIOR=118.2126 * 0.997))
        self.assertGreater(r["pontos"], 0)
        self.assertEqual(r["vies"], "compra")

    def test_dxy_nao_mistura_fred_com_as_demais_fontes(self):
        """BUG 5 — a serie do FRED (DTWEXBGS) e uma escala DIFERENTE do DXY
        classico que fmp/tradingeconomics/investing devolvem. Com "fred" na
        cadeia de fontes, o campo DXY chegou a alternar entre ~118 e ~99
        varias vezes no mesmo dia (16/09), conforme a fonte que respondia
        naquele ciclo — parecia o dolar "saltar" 15% em minutos. "fred" foi
        tirado da cadeia do DXY; continua servindo VIX/PMI normalmente."""
        cadeia_dxy = NS["FONTES_MACRO_WEB"]["DXY"]
        self.assertNotIn("fred", cadeia_dxy)
        self.assertIn("fmp", cadeia_dxy)
        # VIX/PMI nao foram afetados pela correcao.
        self.assertIn("fred", NS["FONTES_MACRO_WEB"]["VIX"])


class TestSaldoAgressaoProxyDeBook(unittest.TestCase):
    """BUG 6 — diagnosticado no dia 16/09/2026: sem Times & Trades com nomes
    de agentes (o caso comum — TemNomesAgentes="nao" em quase toda leitura),
    o percentual de agressao caia num fallback de so 3 valores FIXOS
    (60.0/40.0/50.0, um por categoria "comprador/vendedor/neutro"). Nesse
    dia, 14 sinais de venda SEGUIDOS foram bloqueados com a mensagem
    identica "agressao 60%" — o gatekeeper nunca teve uma leitura de
    verdade pra decidir, so uma de 3 categorias, e ficou preso em
    "comprador" o dia inteiro mesmo com o preco caindo ~43 pontos."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.calc = NS["_calcular_saldo_agressao_pct"]

    def test_usa_profundidade_do_book_quando_falta_tt_com_nomes(self):
        """Reproducao do caso real: categoria "comprador" (que travava em
        60.0 fixo) mas o BOOK em si pesa pra venda — o resultado tem que
        refletir o book, nao a categoria."""
        ag = {
            "saldo_agentes": "comprador",
            "ofertantes_compra": [{"qtde": 300}, {"qtde": 250}, {"qtde": 200},
                                   {"qtde": 150}, {"qtde": 100}],
            "ofertantes_venda": [{"qtde": 500}, {"qtde": 450}, {"qtde": 400},
                                  {"qtde": 350}, {"qtde": 300}],
        }
        r = self.calc(ag)
        self.assertNotEqual(r, 60.0)
        self.assertLess(r, 50.0)  # book pesa pra venda -> tem que ficar abaixo de 50%

    def test_tt_com_nomes_continua_tendo_prioridade(self):
        """Controle: com pressao_compradora/vendedora reais (T&T com nomes),
        a correcao nao pode ter mudado esse caminho, que e o mais confiavel."""
        r = self.calc({"pressao_compradora": 30, "pressao_vendedora": 70,
                        "ofertantes_compra": [{"qtde": 999}], "ofertantes_venda": []})
        self.assertEqual(r, 30.0)

    def test_sem_book_nenhum_continua_neutro(self):
        """Controle: sem nenhum dado, continua 50.0 (nao inventa direcao)."""
        self.assertEqual(self.calc({}), 50.0)
        self.assertEqual(self.calc(None), 50.0)

    def test_sem_tt_e_sem_profundidade_mantem_fallback_categorico(self):
        """Controle: quando nao ha T&T NEM profundidade de book (nada real
        pra usar), o fallback antigo por categoria continua existindo como
        ultimo recurso."""
        self.assertEqual(self.calc({"saldo_agentes": "comprador"}), 60.0)
        self.assertEqual(self.calc({"saldo_agentes": "vendedor"}), 40.0)
        self.assertEqual(self.calc({"saldo_agentes": "neutro"}), 50.0)


if __name__ == "__main__":
    unittest.main()
