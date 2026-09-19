"""Testes da camada continua de indicadores (VWAP Bands/Volume Profile/LVN/
Absorcao) — pedido explicito do usuario apos revisar um replay real (19/09):
esses quatro indicadores ja apareciam no CSV, mas so atuavam em bloqueios
extremos (VWAP Bands/LVN) ou como bonus fixo (Volume Profile), ou quase
nunca disparavam (Absorcao). Esta camada e PARALELA/OBSERVACIONAL — calcula
um score_final_contextual pra auditoria/comparacao em replay, mas NAO altera
contexto["score"]/["score_ponderado"] (o que o gatekeeper usa de verdade).

Rodar de dentro de robo-mini-dolar/:
    python3 -m unittest tests.test_camada_continua -v
"""
import unittest

from tests._mock_env import carregar_engine

NS = None
FAKE_ST = None


def setUpModule():
    global NS, FAKE_ST
    NS, FAKE_ST = carregar_engine()


class TestClassificarVwapBandContinuo(unittest.TestCase):
    """So TRADUZ avaliar_risco_vwap_banda() (fonte unica) pro vocabulario de
    zona/estado — nunca reimplementa o limiar, pra nao divergir do score
    real ja aplicado dentro de classificar_contexto."""

    def setUp(self):
        self.classificar = NS["classificar_vwap_band_continuo"]

    def _bands(self, estado, vwap=5150.0):
        return {"valido": True, "vwap": vwap, "estado": estado,
                "superior_1": vwap + 10, "superior_2": vwap + 20,
                "inferior_1": vwap - 10, "inferior_2": vwap - 20, "fonte": "tela"}

    def test_sem_vwap_bands_fica_indisponivel(self):
        r = self.classificar(5150.0, "compra", None)
        self.assertEqual(r["estado"], "indisponivel")
        self.assertEqual(r["score"], 0)

    def test_dentro_acima_do_centro_zona_entre_vwap_mais1(self):
        r = self.classificar(5152.0, "compra", self._bands("dentro"))
        self.assertEqual(r["zona"], "entre_vwap_mais1")
        self.assertEqual(r["score"], 0)

    def test_dentro_abaixo_do_centro_zona_entre_menos1_vwap(self):
        r = self.classificar(5148.0, "compra", self._bands("dentro"))
        self.assertEqual(r["zona"], "entre_menos1_vwap")

    def test_compra_abaixo_banda1_e_bonus_pullback_nao_penalidade(self):
        """Mesmo sinal ja aplicado ao score real: comprar entre -1 e -2 sigma
        e pullback a favor (bonus +1), nao penalidade -- confirma que a
        traducao de zona bate com avaliar_risco_vwap_banda."""
        r = self.classificar(5140.0, "compra", self._bands("abaixo_banda1"))
        self.assertEqual(r["zona"], "entre_menos2_menos1")
        self.assertEqual(r["score"], 1)
        self.assertEqual(r["risco"], "moderado")

    def test_compra_extensao_superior_e_penalidade_extremo(self):
        r = self.classificar(5175.0, "compra", self._bands("extensao_superior"))
        self.assertEqual(r["zona"], "acima_2sigma")
        self.assertEqual(r["score"], -3)
        self.assertEqual(r["risco"], "extremo")

    def test_venda_extensao_inferior_e_penalidade_extremo(self):
        r = self.classificar(5125.0, "venda", self._bands("extensao_inferior"))
        self.assertEqual(r["zona"], "abaixo_2sigma")
        self.assertEqual(r["score"], -3)
        self.assertEqual(r["risco"], "extremo")

    def test_motivo_sempre_preenchido_quando_valido(self):
        r = self.classificar(5140.0, "compra", self._bands("abaixo_banda1"))
        self.assertTrue(r["motivo"])


class TestClassificarVolumeProfileContinuo(unittest.TestCase):

    def setUp(self):
        self.classificar = NS["classificar_volume_profile_continuo"]

    def _vp(self, poc=5150.0, hvn=None, lvn=None, va_inf=5140.0, va_sup=5160.0):
        return {"valido": True, "poc": poc, "hvn": hvn or [], "lvn": lvn or [],
                "va_inferior": va_inf, "va_superior": va_sup}

    def test_vp_invalido_por_amostra_fica_insuficiente(self):
        r = self.classificar(5150.0, "compra", {"valido": False, "motivo": "amostra insuficiente"})
        self.assertEqual(r["estado"], "insuficiente")

    def test_vp_invalido_por_outro_motivo_fica_indisponivel(self):
        r = self.classificar(5150.0, "compra", {"valido": False, "motivo": "sem variação de preço"})
        self.assertEqual(r["estado"], "indisponivel")

    def test_no_poc_sem_rompimento_fica_neutro(self):
        r = self.classificar(5150.0, "compra", self._vp(poc=5150.0))
        self.assertEqual(r["zona"], "POC")
        self.assertEqual(r["score"], 0)

    def test_no_poc_com_rompimento_a_favor_pontua(self):
        ctx = {"rompimento_dispara": True, "rompimento_direcao": "compra"}
        r = self.classificar(5150.0, "compra", self._vp(poc=5150.0), contexto=ctx)
        self.assertEqual(r["zona"], "POC")
        self.assertEqual(r["score"], 1)

    def test_no_lvn_sem_aceitacao_penaliza(self):
        r = self.classificar(5150.0, "compra", self._vp(poc=5100.0, lvn=[5150.0]))
        self.assertEqual(r["zona"], "LVN")
        self.assertEqual(r["score"], -1)

    def test_no_lvn_com_rompimento_a_favor_pontua(self):
        ctx = {"rompimento_dispara": True, "rompimento_direcao": "venda"}
        r = self.classificar(5150.0, "venda", self._vp(poc=5100.0, lvn=[5150.0]), contexto=ctx)
        self.assertEqual(r["zona"], "LVN")
        self.assertEqual(r["score"], 1)

    def test_no_hvn_dentro_da_area_de_valor_a_favor_pontua(self):
        r = self.classificar(5155.0, "compra", self._vp(poc=5100.0, hvn=[5155.0], va_inf=5140, va_sup=5160))
        self.assertEqual(r["zona"], "HVN")
        self.assertEqual(r["score"], 1)

    def test_no_hvn_dentro_da_area_de_valor_contra_penaliza(self):
        """Venda com preco ACIMA do HVN (ainda nao rompeu pra baixo) e
        "contra" o fluxo que a zona sugere -- diferente do preco exatamente
        no nivel ou abaixo dele, que já favoreceria a continuidade de queda."""
        r = self.classificar(5156.5, "venda", self._vp(poc=5100.0, hvn=[5155.0], va_inf=5140, va_sup=5160))
        self.assertEqual(r["zona"], "HVN")
        self.assertEqual(r["score"], -1)

    def test_dentro_da_area_de_valor_fora_de_poc_hvn_lvn_fica_neutro(self):
        r = self.classificar(5148.0, "compra", self._vp(poc=5100.0, va_inf=5140, va_sup=5160))
        self.assertEqual(r["zona"], "entre_zonas")
        self.assertEqual(r["score"], 0)

    def test_fora_da_area_de_valor_fica_fora_do_perfil(self):
        r = self.classificar(5200.0, "compra", self._vp(poc=5100.0, va_inf=5140, va_sup=5160))
        self.assertEqual(r["zona"], "fora_do_perfil")

    def test_motivo_sempre_preenchido(self):
        r = self.classificar(5150.0, "compra", self._vp(poc=5150.0))
        self.assertTrue(r["motivo"])
        r2 = self.classificar(5150.0, "compra", {"valido": False})
        self.assertTrue(r2["motivo"])


class TestClassificarLvnContinuo(unittest.TestCase):

    def setUp(self):
        self.classificar = NS["classificar_lvn_continuo"]

    def test_sem_lvn_mapeado_fica_nao_aplicavel(self):
        vp = {"valido": True, "lvn": []}
        r = self.classificar(5150.0, "compra", vp)
        self.assertEqual(r["estado"], "nao_aplicavel")

    def test_lvn_longe_do_preco_fica_nao_aplicavel(self):
        vp = {"valido": True, "lvn": [5100.0]}
        r = self.classificar(5150.0, "compra", vp)
        self.assertEqual(r["estado"], "nao_aplicavel")

    def test_lvn_perto_sem_fechamentos_de_aceitacao_penaliza(self):
        vp = {"valido": True, "lvn": [5148.0]}
        r = self.classificar(5150.0, "compra", vp, hist_candles=[])
        self.assertEqual(r["score"], -1)

    def test_lvn_rompido_com_fechamentos_sustentando_pontua(self):
        vp = {"valido": True, "lvn": [5145.0]}
        hist = [{"fechamento": 5150.0}, {"fechamento": 5148.0}, {"fechamento": 5147.0}]
        r = self.classificar(5150.0, "compra", vp, hist_candles=hist)
        self.assertEqual(r["score"], 1)

    def test_vp_indisponivel_fica_indisponivel(self):
        r = self.classificar(5150.0, "compra", {"valido": False})
        self.assertEqual(r["estado"], "indisponivel")


class TestClassificarAbsorcaoContinua(unittest.TestCase):

    def setUp(self):
        self.classificar = NS["classificar_absorcao_continua"]

    def test_sem_preco_fica_indisponivel(self):
        r = self.classificar({"preco_atual": 0}, {})
        self.assertEqual(r["estado"], "indisponivel")

    def test_absorcao_compradora_perto_do_suporte(self):
        dt = {"preco_atual": 5140.0, "minima": 5139.0}
        ctx = {"pos_range": 10, "fluxo_pressao": {"agressao_pct": 40.0},
               "fluxo_desequilibrio": 5, "momentum": "neutro",
               "delta_preco": 0.5, "delta_3": 1.0}
        r = self.classificar(dt, {}, ctx)
        self.assertEqual(r["direcao"], "compradora")
        self.assertGreater(r["score"], 0)

    def test_absorcao_vendedora_perto_da_resistencia(self):
        dt = {"preco_atual": 5160.0, "maxima": 5161.0}
        ctx = {"pos_range": 90, "fluxo_pressao": {"agressao_pct": 60.0},
               "fluxo_desequilibrio": -5, "momentum": "neutro",
               "delta_preco": -0.5, "delta_3": -1.0}
        r = self.classificar(dt, {}, ctx)
        self.assertEqual(r["direcao"], "vendedora")
        self.assertLess(r["score"], 0)

    def test_sem_sinal_objetivo_fica_neutra(self):
        dt = {"preco_atual": 5150.0, "maxima": 5200.0, "minima": 5100.0}
        ctx = {"pos_range": 50, "fluxo_pressao": {"agressao_pct": 50.0},
               "fluxo_desequilibrio": 0, "momentum": "alta",
               "delta_preco": 3.0, "delta_3": 5.0}
        r = self.classificar(dt, {}, ctx)
        self.assertEqual(r["direcao"], "neutra")
        self.assertEqual(r["score"], 0)


class TestCalcularScoreContextualContinuo(unittest.TestCase):
    """Combinador: PARALELO/OBSERVACIONAL — nunca deve mexer em
    contexto['score'] (o real, usado pelo gatekeeper), so devolver um
    score_final proprio pra log/painel."""

    def setUp(self):
        self.calcular = NS["calcular_score_contextual_continuo"]

    def test_preco_invalido_nao_gera_ajuste(self):
        ctx = {"score": 3, "acao_pretendida": "compra"}
        dt = {"preco_atual": 0}
        r = self.calcular(ctx, dt, {})
        self.assertEqual(r["ajuste_total"], 0)
        self.assertEqual(r["score_final"], 3)

    def test_regime_inconsistente_nao_gera_ajuste(self):
        ctx = {"score": 3, "acao_pretendida": "compra", "regime": "inconsistente"}
        dt = {"preco_atual": 5150.0}
        r = self.calcular(ctx, dt, {})
        self.assertEqual(r["ajuste_total"], 0)

    def test_vwap_band_nunca_conta_duas_vezes_no_ajuste_total(self):
        """VWAP Bands ja soma ao score REAL dentro de classificar_contexto
        (avaliar_risco_vwap_banda) -- a camada continua so ECOA esse valor
        pro painel/CSV, nunca soma de novo no ajuste_total."""
        vwap_bands = {"valido": True, "vwap": 5150.0, "estado": "extensao_superior",
                      "superior_1": 5160, "superior_2": 5170, "inferior_1": 5140,
                      "inferior_2": 5130, "fonte": "tela"}
        ctx = {"score": 3, "acao_pretendida": "compra", "vwap_bands": vwap_bands}
        dt = {"preco_atual": 5175.0}
        r = self.calcular(ctx, dt, {})
        self.assertNotEqual(r["vwap_band"]["score"], 0)  # o eco continua != 0...
        self.assertEqual(r["ajuste_total"], 0)  # ...mas nao entra no ajuste_total.

    def test_nao_altera_score_do_contexto_original(self):
        ctx = {"score": 3, "acao_pretendida": "compra"}
        dt = {"preco_atual": 5150.0}
        self.calcular(ctx, dt, {})
        self.assertEqual(ctx["score"], 3)  # combinador e puro: nunca muta o score real.

    def test_ajuste_total_fica_limitado_a_mais_ou_menos_2(self):
        vp = {"valido": True, "poc": 5150.0, "hvn": [], "lvn": [],
              "va_inferior": 5100.0, "va_superior": 5200.0}
        ctx = {"score": 3, "acao_pretendida": "compra", "volume_profile": vp,
               "rompimento_dispara": True, "rompimento_direcao": "compra",
               "pos_range": 10, "fluxo_pressao": {"agressao_pct": 30.0},
               "fluxo_desequilibrio": 10, "momentum": "neutro",
               "delta_preco": 0.2, "delta_3": 0.5}
        dt = {"preco_atual": 5150.0, "minima": 5149.0}
        r = self.calcular(ctx, dt, {})
        self.assertLessEqual(r["ajuste_total"], 2)
        self.assertGreaterEqual(r["ajuste_total"], -2)

    def test_score_final_nunca_sai_da_faixa_0_a_7(self):
        ctx = {"score": 0, "acao_pretendida": "venda"}
        dt = {"preco_atual": 5150.0, "maxima": 5151.0}
        ctx["pos_range"] = 95
        ctx["fluxo_pressao"] = {"agressao_pct": 70.0}
        ctx["fluxo_desequilibrio"] = -10
        ctx["momentum"] = "neutro"
        ctx["delta_preco"] = 0.1
        ctx["delta_3"] = 0.1
        r = self.calcular(ctx, dt, {})
        self.assertGreaterEqual(r["score_final"], 0)
        self.assertLessEqual(r["score_final"], 7)


if __name__ == "__main__":
    unittest.main()
