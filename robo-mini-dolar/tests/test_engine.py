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


if __name__ == "__main__":
    unittest.main()
