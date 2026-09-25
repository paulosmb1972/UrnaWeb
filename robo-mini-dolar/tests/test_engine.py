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


class TestViesMacroPTAXVota(unittest.TestCase):
    """PTAX (cotacaoVenda oficial do BACEN, ja coletada em bcb_ptax) passou
    a votar em vies_macro_consolidado — antes so entrava como checagem de
    disponibilidade do macro, nunca somava/subtraia pontos. Mesmo racional
    de ausencia ja usado pro DXY: sem leitura anterior pra comparar, so
    fica registrado como informativo."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.vies = NS["vies_macro_consolidado"]

    def _macro_base(self, **over):
        base = {"DXY": 118.2126, "VIX": 17.10, "PTAX": 5.1490, "EWZ": 37.90,
                "macro_indisponiveis": [], "macro_indisponiveis_essenciais": []}
        base.update(over)
        return base

    def test_ptax_sem_leitura_anterior_nao_pontua(self):
        r = self.vies(self._macro_base())
        self.assertTrue(any("PTAX" in f and "não pontua" in f for f in r["fatores"]))

    def test_ptax_subindo_meio_ponto_pct_vota_compra(self):
        """PTAX de 5.1490 pra 5.1750 (~+0.50%) — dolar mais caro em reais,
        favorece compra do WDO."""
        r = self.vies(self._macro_base(PTAX_ANTERIOR=5.1490 * (1 - 0.005)))
        self.assertGreater(r["pontos"], 0)
        self.assertTrue(any("PTAX" in f and "mais caro" in f for f in r["fatores"]))

    def test_ptax_caindo_meio_ponto_pct_vota_venda(self):
        r = self.vies(self._macro_base(PTAX_ANTERIOR=5.1490 * 1.005))
        self.assertLess(r["pontos"], 0)
        self.assertTrue(any("PTAX" in f and "mais barato" in f for f in r["fatores"]))

    def test_ptax_variacao_abaixo_do_limiar_nao_pontua(self):
        """Ruido de fixacao intradia normal (~0.05%) nao pode virar sinal."""
        r = self.vies(self._macro_base(DXY_ANTERIOR=118.2126,  # DXY estavel, nao pontua
                                        PTAX_ANTERIOR=5.1490 * (1 - 0.0005)))
        self.assertEqual(r["pontos"], 0)


class TestVeredictoMacroAbaRespeitaReplay(unittest.TestCase):
    """Usuario relatou: a aba Macroeconomicos so mostrava "compra" e sempre
    ~40% de conviccao, em qualquer dia de replay testado. Causa raiz:
    veredito_macro_aba() sempre chamava ler_dados_macro() (o macro.json do
    ultimo pregao REAL, congelado durante o replay -- atualizar_macro_agendado
    nao coleta nesse modo), nunca macro_para_replay(data)."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.veredito_macro_aba = NS["veredito_macro_aba"]
        self._macro_para_replay_orig = NS["macro_para_replay"]
        self._ler_dados_macro_orig = NS["ler_dados_macro"]
        self._chamadas = []
        NS["macro_para_replay"] = lambda data: (
            self._chamadas.append(("replay", data)) or
            {"DXY": 100.0, "DXY_ANTERIOR": 100.0, "VIX": 15.0, "PTAX": 5.10,
             "PTAX_ANTERIOR": 5.10, "disponivel": True})
        NS["ler_dados_macro"] = lambda: (
            self._chamadas.append(("live", None)) or
            {"DXY": 100.0, "DXY_ANTERIOR": 100.0, "VIX": 15.0, "PTAX": 5.10,
             "PTAX_ANTERIOR": 5.10})

    def tearDown(self):
        NS["macro_para_replay"] = self._macro_para_replay_orig
        NS["ler_dados_macro"] = self._ler_dados_macro_orig

    def test_fora_do_replay_usa_ler_dados_macro(self):
        FAKE_ST.session_state["modo_replay"] = False
        self.veredito_macro_aba()
        self.assertEqual(self._chamadas, [("live", None)])

    def test_em_replay_usa_macro_da_data_do_replay(self):
        FAKE_ST.session_state["modo_replay"] = True
        FAKE_ST.session_state["replay_data"] = "2026-09-15"
        self.veredito_macro_aba()
        self.assertEqual(self._chamadas, [("replay", "2026-09-15")])


class TestPmiManualExpiraValidade(unittest.TestCase):
    """Usuario relatou: a aba Macro nunca indicava 'venda', so 'compra' ou
    'neutro' -- em 676 linhas do historico. Causa raiz: o PMI digitado a
    mao (pmi_manufatura/pmi_composto) ficava no session_state PRA SEMPRE
    (widget do Streamlit so muda quando o usuario mexe de novo de verdade)
    e votava com o MESMO peso em toda leitura, dias a fio, mesmo depois do
    PMI real do mes ja ter saido outro -- PMI_EUA apareceu travado em 55.2
    (peso +2, comprador) em 495 das 676 linhas. Com +2 fixo, so um -3 nas
    OUTRAS fontes (DXY+PTAX+EWZ+VIX) derrubava o macro pra venda -- quase
    nunca acontecia. Agora o valor manual so pondera por ate
    PMI_MANUAL_VALIDADE_DIAS depois de digitado (ver _registrar_data_pmi_manual
    / _pmi_manual_esta_fresco)."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.ler_dados_macro = NS["ler_dados_macro"]
        self.datetime = NS["datetime"]
        self.timedelta = NS["timedelta"]
        self.validade = NS["PMI_MANUAL_VALIDADE_DIAS"]

    def test_valor_sem_data_registrada_nao_pondera(self):
        """Valor herdado de antes desta correcao (sem data carimbada) nao
        pode continuar votando silenciosamente pra sempre."""
        FAKE_ST.session_state["pmi_composto"] = 55.2
        r = self.ler_dados_macro()
        self.assertNotIn("PMI_COMPOSTO", r)

    def test_valor_dentro_da_validade_pondera(self):
        FAKE_ST.session_state["pmi_composto"] = 55.2
        FAKE_ST.session_state["pmi_composto_data"] = self.datetime.now().strftime("%Y-%m-%d")
        r = self.ler_dados_macro()
        self.assertEqual(r["PMI_COMPOSTO"], 55.2)

    def test_valor_vencido_nao_pondera_mais(self):
        FAKE_ST.session_state["pmi_manufatura"] = 55.2
        _velha = self.datetime.now() - self.timedelta(days=self.validade + 1)
        FAKE_ST.session_state["pmi_manufatura_data"] = _velha.strftime("%Y-%m-%d")
        r = self.ler_dados_macro()
        self.assertNotIn("PMI_MANUFATURA", r)

    def test_digitar_de_novo_renova_a_validade(self):
        """_registrar_data_pmi_manual (o on_change do widget) e o unico
        jeito de renovar -- simula o usuario digitando de novo."""
        FAKE_ST.session_state["pmi_manufatura"] = 55.2
        _velha = self.datetime.now() - self.timedelta(days=self.validade + 1)
        FAKE_ST.session_state["pmi_manufatura_data"] = _velha.strftime("%Y-%m-%d")
        NS["_registrar_data_pmi_manual"]("pmi_manufatura_data")
        r = self.ler_dados_macro()
        self.assertEqual(r["PMI_MANUFATURA"], 55.2)


class TestMacroAtualOuReplayFonteUnica(unittest.TestCase):
    """A funcao macro_atual_ou_replay() foi reintroduzida depois de ter sido
    perdida numa reversao pra base antiga: 2 call sites (o PMI dentro de
    classificar_contexto e o registro de auditoria do historico) tinham
    voltado a checar a chave morta 'modo_replay_ativo' (nunca setada em
    lugar nenhum -- a de verdade e 'modo_replay'), sempre caindo no ramo ao
    vivo mesmo durante o replay."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.f = NS["macro_atual_ou_replay"]
        self._macro_para_replay_orig = NS["macro_para_replay"]
        self._ler_dados_macro_orig = NS["ler_dados_macro"]
        self._chamadas = []
        NS["macro_para_replay"] = lambda data: (
            self._chamadas.append(("replay", data)) or {"disponivel": True})
        NS["ler_dados_macro"] = lambda: (
            self._chamadas.append(("live", None)) or {"disponivel": True})

    def tearDown(self):
        NS["macro_para_replay"] = self._macro_para_replay_orig
        NS["ler_dados_macro"] = self._ler_dados_macro_orig

    def test_fora_do_replay_usa_ler_dados_macro(self):
        FAKE_ST.session_state["modo_replay"] = False
        self.f()
        self.assertEqual(self._chamadas, [("live", None)])

    def test_em_replay_usa_macro_da_data_do_replay(self):
        FAKE_ST.session_state["modo_replay"] = True
        FAKE_ST.session_state["replay_data"] = "2026-09-15"
        self.f()
        self.assertEqual(self._chamadas, [("replay", "2026-09-15")])

    def test_chave_morta_modo_replay_ativo_nao_afeta_mais_a_escolha(self):
        """Regressao direta do bug: setar a chave ERRADA (que algum codigo
        antigo ainda podia ter deixado no session_state) nao pode fazer a
        funcao escolher replay por engano nem deixar de escolher replay
        quando modo_replay (a chave certa) esta ligada."""
        FAKE_ST.session_state["modo_replay"] = True
        FAKE_ST.session_state["modo_replay_ativo"] = False
        FAKE_ST.session_state["replay_data"] = "2026-09-15"
        self.f()
        self.assertEqual(self._chamadas, [("replay", "2026-09-15")])


class TestColetarIndicadorWebNaoContaminaComCacheAntigo(unittest.TestCase):
    """Usuario pediu: indicador macro que nao foi capturado NAO pode entrar
    na ponderacao da analise, nem em replay nem em tempo real. O fallback
    final de coletar_indicador_web() (cache de ate 24h) nao respeitava
    data_ref -- pra uma data de replay sem nenhuma fonte historica
    respondendo, ele devolvia o ultimo valor de HOJE em vez de marcar o
    indicador como indisponivel, contaminando a leitura daquele dia
    passado com o dado de hoje."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.coletar = NS["coletar_indicador_web"]
        self._cache_get_orig = NS["_cache_macro_get"]
        # nome fora de FONTES_MACRO_WEB -> a cadeia de fontes fica vazia
        # (nenhuma chamada de rede), so restam os dois pontos de cache.
        self.nome = "INDICADOR_INEXISTENTE"
        NS["_cache_macro_get"] = lambda chave, ttl=None: (
            {"valor": 42.0, "fonte": "cache_de_ontem", "data": "2026-09-01"}
            if chave == self.nome else None)

    def tearDown(self):
        NS["_cache_macro_get"] = self._cache_get_orig

    def test_sem_data_ref_usa_cache_antigo_como_ultimo_recurso(self):
        """Controle: modo real preserva a resiliencia de sempre."""
        r = self.coletar(self.nome, data_ref=None)
        self.assertEqual(r["valor"], 42.0)

    def test_com_data_ref_nao_usa_cache_de_hoje_fica_indisponivel(self):
        r = self.coletar(self.nome, data_ref="2020-01-02")
        self.assertIsNone(r["valor"])
        self.assertEqual(r["fonte"], "indisponivel")


class TestBcbPtaxNaoContaminaReplayComValorDeHoje(unittest.TestCase):
    """Mesmo bug, ponto especifico do PTAX: bcb_serie_ultimo() devolve o
    valor MAIS RECENTE da serie (sem filtro de data) -- so faz sentido como
    aproximacao no modo real. Usado tambem com data_ref (replay), contamina
    a leitura do dia passado com o PTAX de hoje."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.bcb_ptax = NS["bcb_ptax"]
        self._valor_em_ou_antes_orig = NS["_bcb_ptax_valor_em_ou_antes"]
        self._serie_ultimo_orig = NS["bcb_serie_ultimo"]
        # Simula o endpoint por dia sempre falhando (BCB fora do ar / feriado
        # alem do numero de tentativas) e a serie SGS "ultimo valor" com um
        # valor de HOJE disponivel.
        NS["_bcb_ptax_valor_em_ou_antes"] = lambda d, tentativas=4: (None, None)
        NS["bcb_serie_ultimo"] = lambda serie, n=1: {"valor": 5.55, "data": "2026-09-21"}

    def tearDown(self):
        NS["_bcb_ptax_valor_em_ou_antes"] = self._valor_em_ou_antes_orig
        NS["bcb_serie_ultimo"] = self._serie_ultimo_orig

    def test_sem_data_ref_cai_para_serie_mais_recente(self):
        """Controle: modo real preserva a resiliencia de sempre."""
        r = self.bcb_ptax(None)
        self.assertIsNotNone(r)
        self.assertEqual(r["valor"], 5.55)

    def test_com_data_ref_nao_usa_serie_mais_recente_devolve_none(self):
        r = self.bcb_ptax("2020-01-02")
        self.assertIsNone(r)


class TestMacroParaReplayNaoTravaComRedeRuim(unittest.TestCase):
    """A aba Macro chama macro_para_replay() a cada RERUN do Streamlit
    (autorefresh geral, mais frequente que o ciclo de analise). Uma coleta
    historica lenta ou pendurada (rede com problema, nao so uma fonte fora
    do ar) sem teto de tempo nem cache de falha pode travar o render da aba
    inteira: cada rerun tenta de novo a mesma coleta lenta."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.macro_para_replay = NS["macro_para_replay"]
        self._orig = {k: NS[k] for k in (
            "coletar_macro_web", "_cache_macro_ler", "_cache_macro_gravar",
            "TIMEOUT_MACRO_REPLAY_SEGUNDOS", "RESFRIAMENTO_MACRO_REPLAY_FALHA_SEGUNDOS")}
        self._cache = {}
        NS["_cache_macro_ler"] = lambda: self._cache
        NS["_cache_macro_gravar"] = lambda c: self._cache.update(c)

    def tearDown(self):
        NS.update(self._orig)

    def test_coleta_que_nunca_retorna_e_limitada_pelo_teto_de_tempo(self):
        """A coleta simula uma rede pendurada (dorme muito mais que o teto).
        macro_para_replay tem que devolver indisponivel dentro de um tempo
        curto, nunca esperar a coleta terminar."""
        import time as _time
        def _coleta_pendurada(data_ref=None):
            _time.sleep(5)   # bem mais que o teto usado no teste abaixo
            return {"PTAX": 5.10, "DXY": 100.0, "VIX": 15.0}
        NS["coletar_macro_web"] = _coleta_pendurada
        NS["TIMEOUT_MACRO_REPLAY_SEGUNDOS"] = 0.2

        t0 = _time.time()
        r = self.macro_para_replay("2026-09-16")
        decorrido = _time.time() - t0

        self.assertLess(decorrido, 2.0, "nao pode esperar a coleta pendurada terminar")
        self.assertFalse(r.get("disponivel"))

    def test_falha_fica_em_resfriamento_nao_martela_a_cada_rerun(self):
        """Depois de uma falha, uma chamada logo em seguida (equivalente a
        outro rerun do streamlit segundos depois) nao deve tentar de novo —
        devolve o mesmo resultado cacheado sem chamar coletar_macro_web."""
        chamadas = []
        def _coleta_falha(data_ref=None):
            chamadas.append(data_ref)
            return {}
        NS["coletar_macro_web"] = _coleta_falha
        NS["TIMEOUT_MACRO_REPLAY_SEGUNDOS"] = 5
        NS["RESFRIAMENTO_MACRO_REPLAY_FALHA_SEGUNDOS"] = 120

        r1 = self.macro_para_replay("2026-09-17")
        r2 = self.macro_para_replay("2026-09-17")

        self.assertFalse(r1.get("disponivel"))
        self.assertEqual(r1, r2)
        self.assertEqual(len(chamadas), 1)

    def test_sucesso_fica_cacheado_para_o_dia_inteiro(self):
        chamadas = []
        def _coleta_ok(data_ref=None):
            chamadas.append(data_ref)
            return {"PTAX": 5.10, "PTAX_ANTERIOR": 5.08}
        NS["coletar_macro_web"] = _coleta_ok
        NS["TIMEOUT_MACRO_REPLAY_SEGUNDOS"] = 5

        r1 = self.macro_para_replay("2026-09-18")
        r2 = self.macro_para_replay("2026-09-18")

        self.assertTrue(r1.get("disponivel"))
        self.assertEqual(r1, r2)
        self.assertEqual(len(chamadas), 1)


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


class TestParseListaNumerosPt(unittest.TestCase):
    """parse_lista_numeros_pt() transcreve a linha crua de vwap_banda_lista
    (formato brasileiro, separada por ';') sem exigir que a IA saiba
    ordenar/rotular cada numero — so precisa listar o que ve."""

    def setUp(self):
        self.parse = NS["parse_lista_numeros_pt"]

    def test_lista_completa_formato_brasileiro(self):
        r = self.parse("5.175,85;5.193,04;5.210,24;5.141,46;5.124,26;5.107,07")
        self.assertEqual(r, [5175.85, 5193.04, 5210.24, 5141.46, 5124.26, 5107.07])

    def test_aceita_pipe_como_separador(self):
        self.assertEqual(self.parse("5175,85|5141,46"), [5175.85, 5141.46])

    def test_vazio_devolve_lista_vazia(self):
        self.assertEqual(self.parse(""), [])
        self.assertEqual(self.parse(None), [])

    def test_ignora_pedaco_ilegivel_sem_lancar_excecao(self):
        r = self.parse("5175,85;;abc;5141,46")
        self.assertEqual(r, [5175.85, 5141.46])


class TestVwapBandsDaTela(unittest.TestCase):
    """calcular_vwap_bands() passa a preferir o indicador real "VWAP Band"
    da tela (bandas_vwap_da_tela) — disponivel desde a primeira leitura do
    dia, sem depender de hist_leituras acumulado. Caso real do pedido: WDOV26
    com VWAP D = 5158,65 e VWAP Band mostrando 3 desvios simetricos de cada
    lado (5175,85/5193,04/5210,24 acima; 5141,46/5124,26/5107,07 abaixo)."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.calcular = NS["calcular_vwap_bands"]

    def _dt(self, preco, **over):
        base = {
            "preco_atual": preco, "vwap": 5158.65,
            "vwap_banda_lista": "5175,85;5193,04;5210,24;5141,46;5124,26;5107,07",
        }
        base.update(over)
        return base

    def test_usa_banda_da_tela_mesmo_sem_historico_nenhum(self):
        """Sem NENHUMA leitura acumulada (hist=[]), a estimativa estatistica
        antiga devolveria 'indisponivel' — a banda da tela tem que valer
        de qualquer forma, ja na primeira leitura do dia."""
        r = self.calcular(self._dt(5160.0), hist=[])
        self.assertTrue(r["valido"])
        self.assertEqual(r["fonte"], "tela")
        self.assertEqual(r["vwap"], 5158.65)
        self.assertEqual(r["superior_1"], 5175.85)
        self.assertEqual(r["superior_2"], 5210.24)
        self.assertEqual(r["inferior_1"], 5141.46)
        self.assertEqual(r["inferior_2"], 5107.07)

    def test_estado_extensao_superior_bloqueia_compra_no_extremo(self):
        """Preco alem do +2sigma da tela: mesmo estado que a estimativa
        antiga ja usava para vetar entrada sem ancora (avaliar_risco_vwap_banda
        nao precisou mudar - so o calculo do input mudou)."""
        r = self.calcular(self._dt(5215.0), hist=[])
        self.assertEqual(r["estado"], "extensao_superior")

    def test_estado_dentro_quando_preco_entre_as_bandas_1(self):
        r = self.calcular(self._dt(5160.0), hist=[])
        self.assertEqual(r["estado"], "dentro")

    def test_sem_vwap_banda_lista_cai_para_estimativa_antiga(self):
        """Sem o campo (indicador nao capturado/nao visivel), comportamento
        100% igual ao de antes desta mudanca: sem historico suficiente,
        continua 'indisponivel', fonte 'calculado'."""
        dt = {"preco_atual": 5160.0, "vwap": 5158.65, "vwap_banda_lista": ""}
        r = self.calcular(dt, hist=[])
        self.assertFalse(r["valido"])
        self.assertEqual(r["fonte"], "calculado")

    def test_lista_so_com_valores_de_um_lado_cai_para_estimativa_antiga(self):
        """Leitura manca (so achou os valores ACIMA do centro): nao da pra
        montar banda 1/2 dos dois lados, entao nao usa a tela - evita
        gatekeeper/score decidirem com banda so de um lado."""
        dt = {"preco_atual": 5160.0, "vwap": 5158.65,
              "vwap_banda_lista": "5175,85;5193,04"}
        r = self.calcular(dt, hist=[])
        self.assertEqual(r.get("fonte"), "calculado")

    def test_vwap_banda_lista_com_apenas_1_desvio_de_cada_lado(self):
        """Indicador configurado com so 1 desvio (2 numeros no total): banda
        1 e banda 2 empatam no mesmo valor, mas continua valido e usavel."""
        dt = {"preco_atual": 5160.0, "vwap": 5158.65,
              "vwap_banda_lista": "5175,85;5141,46"}
        r = self.calcular(dt, hist=[])
        self.assertTrue(r["valido"])
        self.assertEqual(r["superior_1"], r["superior_2"])
        self.assertEqual(r["inferior_1"], r["inferior_2"])


class TestTsEventoModoRealIgnoraDataReplay(unittest.TestCase):
    """Export real de 17/09/2026 mostrou DataEvento gravado em 2020 e 2024
    em linhas com ModoReplay=nao (ao vivo), minutos depois do app iniciar,
    enquanto DataRegistro (sempre datetime.now()) continuava certo. Causa:
    ts_evento() em modo real lia dados_tela["data_replay"]/["hora_replay"]
    ANTES do relogio do sistema -- e a IA e instruida a tentar ler esses
    dois campos em QUALQUER modo, podendo confundir outro elemento da tela
    com uma data de replay mesmo estando ao vivo. Fora do modo replay, o
    unico relogio confiavel e o do sistema."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        FAKE_ST.session_state["modo_replay"] = False
        self.ts_evento = NS["ts_evento"]

    def test_ignora_data_replay_alucinada_fora_do_modo_replay(self):
        dt = {"data_replay": "2020-09-16", "hora_replay": "09:00:00"}
        r = self.ts_evento(dt)
        self.assertNotIn("2020-09-16", r)
        from datetime import datetime
        self.assertTrue(r.startswith(datetime.now().strftime("%Y-%m-%d")))

    def test_sem_data_replay_nenhuma_continua_usando_relogio_do_sistema(self):
        """Controle: comportamento de sempre (sem os campos) inalterado."""
        r = self.ts_evento({})
        from datetime import datetime
        self.assertTrue(r.startswith(datetime.now().strftime("%Y-%m-%d")))

    def test_modo_replay_continua_usando_data_da_tela_normalmente(self):
        """Controle: a correcao e SO pro modo real -- em replay, a leitura
        da tela continua tendo prioridade, como sempre."""
        FAKE_ST.session_state["modo_replay"] = True
        FAKE_ST.session_state["replay_data"] = "2026-01-01"
        FAKE_ST.session_state["replay_hora"] = "09:00"
        dt = {"data_replay": "2026-07-28", "hora_replay": "09:00:31"}
        r = self.ts_evento(dt)
        self.assertEqual(r, "2026-07-28 09:00:31")


class TestRodarCicloAutomaticoRegistraDesfecho(unittest.TestCase):
    """_rodar_ciclo_automatico e a logica compartilhada entre o gatilho do
    proprio rerun do Streamlit e a thread em segundo plano
    (_loop_analise_automatica_background, criada pra corrigir o ciclo de 5
    min travando quando a aba do navegador fica atras dos graficos do
    Profit -- navegadores pausam o timer de abas escondidas/minimizadas).
    Cobre so a contabilizacao dos contadores auto_analise_*, que e a parte
    que ja tinha ficado quebrada silenciosamente antes."""

    def setUp(self):
        FAKE_ST.session_state.clear()
        self.rodar = NS["_rodar_ciclo_automatico"]
        self._executar_orig = NS["executar_analise"]

    def tearDown(self):
        NS["executar_analise"] = self._executar_orig

    def test_sucesso_incrementa_tentativas_e_salvos(self):
        NS["executar_analise"] = lambda: FAKE_ST.session_state.__setitem__(
            "ultimo_diagnostico", "ARMADO: COMPRA a 5170.00")
        self.rodar("ciclo_5min")
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_tentativas"), 1)
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_salvos"), 1)
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_duplicados", 0), 0)
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_erros", 0), 0)

    def test_duplicado_incrementa_duplicados_nao_salvos(self):
        NS["executar_analise"] = lambda: FAKE_ST.session_state.__setitem__(
            "ultimo_diagnostico", "ESPERA: ESPERA a 5170.00 | HIST: Duplicado.")
        self.rodar("ciclo_5min")
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_duplicados"), 1)
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_salvos", 0), 0)

    def test_excecao_incrementa_erros_e_registra_ultimo_erro(self):
        def _falha():
            raise RuntimeError("falha simulada de captura")
        NS["executar_analise"] = _falha
        self.rodar("ciclo_5min")
        self.assertEqual(FAKE_ST.session_state.get("auto_analise_erros"), 1)
        self.assertIn("falha simulada", str(FAKE_ST.session_state.get("ultimo_erro_ciclo")))


class TestGatekeeperTendenciaAcimaDoFluxo(unittest.TestCase):
    """Caso real relatado pelo usuario: preco caiu de 5171 para 5147 (24
    pontos) e o sistema NUNCA armou venda. Causa raiz: o gatekeeper
    reavaliava a trava de "fluxo direcional" (SaldoAgressaoPct/ViesFluxo)
    de forma independente da classificacao, sem a mesma valvula de escape
    "tendencia acima do fluxo" que classificar_contexto ja usa -- entao
    vetava sozinho uma venda que a tendencia/momentum ja confirmavam,
    so porque o proxy de agressao (sem nomes de corretora no plano de
    dados deste usuario) nunca cruzava o limiar de 42%/58%."""

    def setUp(self):
        self.avaliar = NS["_avaliar_travas"]

    def _gatilho_base(self, **over):
        base = {
            "Acao": "venda", "Momentum": "baixa", "DistanciaMM9": 2.0,
            "AncoraEntrada": "nao", "FluxoLido": "sim",
            "SaldoAgressaoPct": 50.0, "ViesFluxo": "indefinido",
            "PosRange": 50.0, "Regime": "trend_down", "Score": 3,
        }
        base.update(over)
        return base

    def test_sem_tendencia_definida_continua_bloqueando_como_antes(self):
        """Controle: fora de um regime de tendencia confirmada, a trava
        continua identica a antes da correcao -- nao ficou permissiva demais."""
        g = self._gatilho_base(Regime="lateral")
        motivo = self.avaliar(g)
        self.assertIsNotNone(motivo)
        self.assertIn("Fluxo sem direcao vendedora", motivo)

    def test_tendencia_de_baixa_confirmada_libera_venda_com_fluxo_neutro(self):
        """Regime trend_down + momentum baixa confirmando: a venda arma
        mesmo com agressao neutra (50%) -- exatamente o cenario da queda
        de 5171 para 5147 relatada."""
        g = self._gatilho_base(Regime="trend_down", Momentum="baixa", SaldoAgressaoPct=50.0)
        motivo = self.avaliar(g)
        self.assertIsNone(motivo)

    def test_pullback_down_tambem_conta_como_tendencia_de_baixa(self):
        g = self._gatilho_base(Regime="pullback_down", Momentum="baixa_forte", DistanciaMM9=0.0)
        motivo = self.avaliar(g)
        self.assertIsNone(motivo)

    def test_tendencia_confirmada_libera_venda_mesmo_com_fluxo_fortemente_contrario(self):
        """Mesma filosofia ja usada dentro de classificar_contexto (ver
        "TENDENCIA ACIMA DO FLUXO"): quando a tendencia E o momentum
        confirmam, o fluxo contrario (mesmo forte) nunca vira 'espera' la —
        so reduz o score, meses antes desta trava. O gatekeeper precisa
        replicar a MESMA regra, senao ele veta sozinho o que a classificacao
        ja deixou passar (com score menor)."""
        g = self._gatilho_base(Regime="trend_down", Momentum="baixa", SaldoAgressaoPct=70.0)
        motivo = self.avaliar(g)
        self.assertIsNone(motivo)

    def test_tendencia_de_alta_confirmada_libera_compra_com_fluxo_neutro(self):
        """Mesma correcao, simetrica pro lado de compra."""
        g = self._gatilho_base(Acao="compra", Momentum="alta", Regime="trend_up",
                                SaldoAgressaoPct=50.0)
        motivo = self.avaliar(g)
        self.assertIsNone(motivo)

    def test_tendencia_a_favor_mas_perseguindo_ponta_do_range_nao_forca_liberacao(self):
        """pos_range fora de 20-80 e sem momentum a favor explicito nao ativa
        a valvula de escape -- evita perseguir a ponta do movimento so
        porque o regime e de tendencia."""
        g = self._gatilho_base(Regime="trend_down", Momentum="neutro", PosRange=5.0)
        motivo = self.avaliar(g)
        self.assertIsNotNone(motivo)


if __name__ == "__main__":
    unittest.main()
