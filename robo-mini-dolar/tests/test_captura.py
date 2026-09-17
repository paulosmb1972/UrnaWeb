"""Testes da reforma da camada de captura de tela/janelas do Profit
(classificacao de janela, validacao de imagem, coordenada manual e o
selecionar/capturar hibrido) — diagnosticado que o grafico (GPU) so
captura com BitBlt e a janela VISIVEL na tela, e paineis de tabela
(SuperDOM/T&T/Livro/Agentes) precisam estar "destacados" como janela
propria pro PrintWindow os encontrar em segundo plano.

So cobre o que da pra testar sem Windows de verdade: as funcoes puras
(classificar_tipo_janela_profit, imagem_valida_para_analise) e o
comportamento de fallback seguro das que dependem de win32 (sempre
mockado neste ambiente — ver tests/_mock_env.py).

Rodar de dentro de robo-mini-dolar/:
    python3 -m unittest tests.test_captura -v
"""
import os
import unittest

from PIL import Image

from tests._mock_env import carregar_engine

NS = None
FAKE_ST = None


def setUpModule():
    global NS, FAKE_ST
    NS, FAKE_ST = carregar_engine()


class TestClassificarTipoJanelaProfit(unittest.TestCase):
    """A classificacao e usada so como desempate/diagnostico — nunca deve
    lancar excecao, e tem que respeitar as palavras-chave e a proporcao da
    janela descritas no pedido de correcao."""

    def setUp(self):
        self.classificar = NS["classificar_tipo_janela_profit"]

    def test_grafico_por_titulo(self):
        r = self.classificar("WDOV26 - Gráfico Candles", "", 1200, 700)
        self.assertEqual(r["tipo"], "grafico")
        self.assertGreater(r["confianca"], 0)

    def test_superdom_por_titulo_estreito_e_alto(self):
        r = self.classificar("SuperDOM WDOV26", "", 300, 800)
        self.assertEqual(r["tipo"], "superdom")

    def test_times_trades_por_titulo(self):
        r = self.classificar("Times & Trades - Ordem Original", "", 500, 600)
        self.assertEqual(r["tipo"], "times_trades")

    def test_agentes_por_titulo(self):
        r = self.classificar("Ranking de Corretoras / Agentes", "", 500, 400)
        self.assertEqual(r["tipo"], "agentes")

    def test_livro_por_titulo(self):
        r = self.classificar("Livro de Ofertas - Profundidade", "", 400, 500)
        self.assertEqual(r["tipo"], "livro")

    def test_grade_de_cotacoes_por_titulo(self):
        r = self.classificar("Grade de Cotações", "", 900, 300)
        self.assertEqual(r["tipo"], "grade")

    def test_titulo_generico_sem_palavra_chave_fica_desconhecido(self):
        r = self.classificar("Explorador de Arquivos", "", 800, 600)
        self.assertEqual(r["tipo"], "desconhecido")
        self.assertEqual(r["confianca"], 0)

    def test_titulo_so_com_ticker_fica_desconhecido_mas_pontua_pouco(self):
        """Titulo generico demais (so o ticker, sem indicar QUAL painel) —
        nao pode virar "grafico" nem qualquer outro tipo especifico so por
        ter o ticker; fica "desconhecido" com confianca baixa, pra
        selecionar_melhor_janela usar so como ultimo recurso."""
        r = self.classificar("WDOV26", "", 500, 500)
        self.assertEqual(r["tipo"], "desconhecido")

    def test_nunca_lanca_excecao_com_entrada_invalida(self):
        r = self.classificar(None, None, "abc", None)
        self.assertEqual(r["tipo"], "desconhecido")
        self.assertIn("motivo", r)


class TestImagemValidaParaAnalise(unittest.TestCase):
    """Validacao mais completa que _imagem_esta_em_branco() — usada pelos
    metodos novos (capturar_bitblt_desktop/capturar_printwindow/
    capturar_janela_hibrida) pra nunca aceitar captura preta/branca/
    uniforme como sucesso."""

    def setUp(self):
        self.validar = NS["imagem_valida_para_analise"]

    def test_imagem_none_e_invalida(self):
        ok, motivo = self.validar(None)
        self.assertFalse(ok)
        self.assertIn("ausente", motivo)

    def test_imagem_toda_preta_e_invalida(self):
        img = Image.new("RGB", (200, 200), color=(0, 0, 0))
        ok, motivo = self.validar(img)
        self.assertFalse(ok)

    def test_imagem_toda_branca_e_invalida(self):
        img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        ok, motivo = self.validar(img)
        self.assertFalse(ok)

    def test_imagem_muito_pequena_e_invalida(self):
        img = Image.new("RGB", (10, 10), color=(120, 60, 200))
        ok, motivo = self.validar(img)
        self.assertFalse(ok)
        self.assertIn("pequena", motivo)

    def test_imagem_com_conteudo_real_e_valida(self):
        """Xadrez preto/branco: variancia alta, sem cor unica dominante —
        simula uma captura de tela de verdade (texto/graficos tem
        contraste), diferente de um frame preto/branco solido."""
        img = Image.new("RGB", (200, 200))
        pix = img.load()
        for x in range(200):
            for y in range(200):
                cor = 255 if (x // 10 + y // 10) % 2 == 0 else 0
                pix[x, y] = (cor, cor, cor)
        ok, motivo = self.validar(img)
        self.assertTrue(ok, motivo)


class TestCapturarRectManual(unittest.TestCase):
    """Fallback por coordenada manual via variavel de ambiente — prioridade
    maxima quando definida, mas ZERO efeito colateral quando nao definida
    (nao pode mudar o comportamento de quem nunca configurou isso)."""

    def setUp(self):
        self.capturar = NS["capturar_rect_manual"]
        self._env_bak = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_bak)

    def test_sem_variavel_definida_nao_faz_nada(self):
        os.environ.pop("CAPTURA_TESTE_RECT", None)
        img, msg = self.capturar("CAPTURA_TESTE_RECT", "Teste")
        self.assertIsNone(img)
        self.assertIsNone(msg)

    def test_variavel_mal_formatada_devolve_motivo_claro(self):
        os.environ["CAPTURA_TESTE_RECT"] = "isso nao e uma coordenada"
        img, msg = self.capturar("CAPTURA_TESTE_RECT", "Teste")
        self.assertIsNone(img)
        self.assertIn("mal formatada", msg)

    def test_variavel_com_numeros_errados_tambem_da_motivo_claro(self):
        os.environ["CAPTURA_TESTE_RECT"] = "10,20,30"  # faltou o 4o numero
        img, msg = self.capturar("CAPTURA_TESTE_RECT", "Teste")
        self.assertIsNone(img)
        self.assertIn("mal formatada", msg)


class TestSelecionarMelhorJanelaSemWindows(unittest.TestCase):
    """Sem Windows de verdade (win32gui mockado neste ambiente),
    listar_janelas_profit_classificadas() sempre devolve lista vazia — o
    importante e que selecionar_melhor_janela() nunca quebre nesse caso,
    so devolva None (nenhuma janela encontrada)."""

    def test_sem_janelas_devolve_none_sem_lancar_excecao(self):
        selecionar = NS["selecionar_melhor_janela"]
        self.assertIsNone(selecionar("grafico"))
        self.assertIsNone(selecionar("superdom", palavras=["superdom"]))


class TestDiagnosticarJanelasProfitSemWindows(unittest.TestCase):
    """diagnosticar_janelas_profit() e so leitura de diagnostico (item 17 do
    pedido de reforma) — sem Windows de verdade tem que continuar devolvendo
    lista vazia, sem lancar excecao, exatamente como a versao antiga."""

    def test_sem_janelas_devolve_lista_vazia_sem_lancar_excecao(self):
        diagnosticar = NS["diagnosticar_janelas_profit"]
        self.assertEqual(diagnosticar(), [])


if __name__ == "__main__":
    unittest.main()
