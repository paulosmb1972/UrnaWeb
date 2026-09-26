"""Motor de deteccao/classificacao de fluxo e microestrutura.

Modulo independente (nao importado ainda por robo_mini_dolar.py). Projetado
para alimentar a aba Liquidez futuramente, substituindo/complementando
calcular_pressao_fluxo().

RESTRICAO ESTRUTURAL DO AMBIENTE — leia antes de calibrar limiares:
Neste app os dados de book/T&T nao vem de um feed de ticks (WebSocket/DDE/
ProfitDLL). Vem de leitura periodica de tela via IA de visao, a cada
INTERVALO_ANALISE_SEGUNDOS (hoje 300s = 5 min). Isso muda o que da pra
afirmar:

- Sinais que dependem de granularidade FINA (ordens escondidas por
  reaparicao rapida de lote, empilhamento tick-a-tick, retirada de liquidez
  no instante que precede o movimento) so podem ser observados de forma
  BORRADA -- comparando snapshots separados por minutos, nao por segundos.
  Por design, esses ficam limitados a INFERENCIA_FRACA ou INDEFINIDO na
  imensa maioria das leituras, mesmo com muita evidencia acumulada --
  nunca sobem a LEITURA_DIRETA nem, sem participante, a INFERENCIA_FORTE.
- Sinais que ja funcionam em granularidade de "candle" (dominancia de
  fluxo, absorcao, rompimento com aceitacao/falso, defesa de preco,
  desequilibrio de execucao) tem uma leitura razoavel mesmo a cada 5 min,
  igual ao que calcular_pressao_fluxo() ja faz hoje.
- Nomes de corretora/participante no book: hoje SEMPRE ausentes neste
  ambiente (TemNomesAgentes = "nao" em ~100% das leituras registradas no
  historico) -- o motor tem que funcionar 100% no MODO_AGREGADO por
  enquanto, e so acender o MODO_PARTICIPANTE se um dia isso mudar (ex.:
  migracao para ProfitDLL com corretora identificada).

Se e quando o ambiente ganhar um feed de ticks reais (ProfitDLL, mencionado
como possibilidade futura), a MESMA arquitetura (JanelaFluxo alimentada por
TradeEvent/BookSnapshot) funciona sem redesenhar nada -- so os limiares de
config.py deste modulo mudam (janela mais curta, minimo de amostras maior
por segundo, tetos de confianca liberados).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple


# =============================================================================
# BLOCO 2 — MODELO DE DADOS
# =============================================================================

class ModoDados(str, Enum):
    AGREGADO = "agregado"          # book sem identificacao de participante
    PARTICIPANTE = "participante"  # book com corretora/agente identificado


class NivelConfianca(str, Enum):
    LEITURA_DIRETA = "leitura_direta"      # o dado em si ja afirma o fato
    INFERENCIA_FORTE = "inferencia_forte"  # varias evidencias convergentes
    INFERENCIA_FRACA = "inferencia_fraca"  # poucas evidencias ou ambiguas
    INDEFINIDO = "indefinido"              # dado insuficiente -- nunca chuta


class Perfil(str, Enum):
    CONSERVADOR = "conservador"
    AGRESSIVO = "agressivo"


@dataclass
class NivelBook:
    """Um preco do book, num instante. participante_* so vem preenchido
    quando o ambiente realmente identifica o agente -- nunca inventar."""
    preco: float
    qtd_compra: float = 0.0
    qtd_venda: float = 0.0
    participante_compra: Optional[str] = None
    participante_venda: Optional[str] = None


@dataclass
class BookSnapshot:
    """Uma leitura do book num instante. 'fonte' registra de onde veio,
    pra auditoria (ex.: "visao_ia_profit", "profitdll")."""
    timestamp: datetime
    niveis: List[NivelBook]
    modo: ModoDados
    fonte: str
    preco_referencia: float = 0.0

    def nivel(self, preco: float, tolerancia: float) -> Optional[NivelBook]:
        for n in self.niveis:
            if abs(n.preco - preco) <= tolerancia:
                return n
        return None


@dataclass
class TradeEvent:
    """Um negocio executado. Em ambiente sem T&T tick-a-tick, pode ser
    sintetizado a partir do resumo de agressao lido por leitura (ver
    EventoFluxoAgregado.para_trade_sintetico)."""
    timestamp: datetime
    preco: float
    quantidade: float
    lado_agressor: str    # "compra" | "venda" | "indefinido"
    participante: Optional[str] = None


@dataclass
class EventoFluxoAgregado:
    """Uma leitura periodica (o que o app ja produz hoje a cada ciclo):
    resumo de fluxo entre a leitura anterior e esta, sem tick a tick.
    E o formato de entrada REAL deste ambiente ate que exista feed de
    ticks -- os detectores tratam isso como um TradeEvent/BookSnapshot de
    baixa resolucao, nunca fingindo ser tick real."""
    timestamp: datetime
    preco_abertura: float
    preco_fechamento: float
    maxima: float
    minima: float
    volume_total: float
    agressao_compradora_pct: float   # 0-100, ja calculado hoje em calcular_pressao_fluxo
    agressao_vendedora_pct: float    # 0-100
    delta: float                     # compras agressoras - vendas agressoras (unidades da fonte)
    book: Optional[BookSnapshot] = None


@dataclass
class Evidencia:
    descricao: str
    peso: float          # positivo = a favor da direcao/sinal, negativo = contra
    fonte_dado: str = ""  # qual campo/metrica originou isso (auditoria)


@dataclass
class MetricasJanela:
    """Saida pura de calculo (sem juizo de valor) sobre a janela corrente.
    Cada detector le daqui, nunca recalcula do zero."""
    n_leituras: int = 0
    delta_acumulado: float = 0.0
    delta_medio: float = 0.0
    persistencia_nivel: Dict[float, int] = field(default_factory=dict)   # preco -> nº leituras seguidas dentro da faixa
    variacao_lote_nivel: Dict[float, List[float]] = field(default_factory=dict)  # preco -> serie de qtd exposta
    deslocamento_preco_pct: float = 0.0
    volume_total_janela: float = 0.0
    amplitude_janela: float = 0.0
    reapareceu_no_mesmo_nivel: Dict[float, int] = field(default_factory=dict)  # preco -> quantas vezes sumiu+voltou
    participantes_recorrentes: Dict[str, int] = field(default_factory=dict)     # so populado em modo participante


@dataclass
class SinalDetectado:
    tipo: str                       # chave do sinal, ex.: "ordem_escondida"
    presente: bool                  # True = sinal disparou, False = avaliado e descartado
    direcao: Optional[str]          # "compra" | "venda" | None (sinais sem lado, ex. empilhamento simetrico)
    score: float
    confianca: NivelConfianca
    evidencias_favor: List[Evidencia]
    evidencias_contra: List[Evidencia]
    modo_dados: ModoDados
    detalhe: str = ""


@dataclass
class ClassificacaoFluxo:
    """Saida final do motor para 1 instante."""
    timestamp: datetime
    modo_dados: ModoDados
    sinais: Dict[str, SinalDetectado]
    resumo: str


# =============================================================================
# BLOCO 4 (parte 1) — CONFIGURACAO / PARAMETROS AJUSTAVEIS
# =============================================================================

@dataclass
class ConfigMotorFluxo:
    perfil: Perfil = Perfil.CONSERVADOR

    # janela temporal
    janela_leituras: int = 12          # nº de EventoFluxoAgregado mantidos (12 x 5min = 1h)
    janela_minutos_max: int = 90       # descarta leituras mais velhas que isso

    # tolerancia de faixa de preco (pontos) -- "mesmo nivel" na pratica
    tolerancia_faixa_pts: float = 1.0

    # limites por sinal
    min_execucoes_mesmo_nivel: int = 3         # ordem escondida / absorcao
    volume_minimo_absorcao: float = 300.0      # unidades da fonte (financeiro ou contratos, conforme captura)
    delta_minimo_dominancia: float = 0.15      # fracao do volume da janela
    persistencia_minima_nivel: int = 2         # nº leituras seguidas no mesmo nivel
    deslocamento_max_absorcao_pct: float = 0.15  # % da amplitude tipica -- "pouco deslocamento"
    reaparicoes_min_reposicao: int = 2
    aceitacao_min_leituras_fora_faixa: int = 2  # rompimento com aceitacao
    retorno_max_pts_rompimento_falso: float = 1.5

    # scoring
    limiar_forte: float = 70.0
    limiar_fraco: float = 40.0
    minimo_amostras_para_pontuar: int = 3

    # teto de confianca por falta de granularidade (ver docstring do modulo)
    teto_confianca_sem_participante: NivelConfianca = NivelConfianca.INFERENCIA_FORTE
    teto_confianca_sinais_finos_agregado: NivelConfianca = NivelConfianca.INFERENCIA_FRACA

    @staticmethod
    def conservador() -> "ConfigMotorFluxo":
        return ConfigMotorFluxo(
            perfil=Perfil.CONSERVADOR,
            min_execucoes_mesmo_nivel=4,
            persistencia_minima_nivel=3,
            limiar_forte=80.0,
            limiar_fraco=55.0,
            minimo_amostras_para_pontuar=4,
        )

    @staticmethod
    def agressivo() -> "ConfigMotorFluxo":
        return ConfigMotorFluxo(
            perfil=Perfil.AGRESSIVO,
            min_execucoes_mesmo_nivel=2,
            persistencia_minima_nivel=1,
            limiar_forte=60.0,
            limiar_fraco=30.0,
            minimo_amostras_para_pontuar=2,
        )


# =============================================================================
# JANELA (buffer rolante) — entrada de todos os detectores
# =============================================================================

class JanelaFluxo:
    """Buffer rolante de EventoFluxoAgregado. Unica fonte de estado
    compartilhado entre detectores -- eles nunca guardam estado proprio."""

    def __init__(self, config: ConfigMotorFluxo):
        self.config = config
        self._eventos: List[EventoFluxoAgregado] = []

    def adicionar(self, evento: EventoFluxoAgregado) -> None:
        self._eventos.append(evento)
        limite_tempo = evento.timestamp - timedelta(minutes=self.config.janela_minutos_max)
        self._eventos = [e for e in self._eventos if e.timestamp >= limite_tempo]
        self._eventos = self._eventos[-self.config.janela_leituras:]

    @property
    def eventos(self) -> List[EventoFluxoAgregado]:
        return list(self._eventos)

    @property
    def modo(self) -> ModoDados:
        for e in reversed(self._eventos):
            if e.book is not None:
                return e.book.modo
        return ModoDados.AGREGADO

    def tem_amostras_suficientes(self) -> bool:
        return len(self._eventos) >= self.config.minimo_amostras_para_pontuar


# =============================================================================
# BLOCO 3 (parte 1) — CALCULO DE METRICAS (puro, sem juizo de valor)
# =============================================================================

def calcular_metricas(janela: JanelaFluxo) -> MetricasJanela:
    eventos = janela.eventos
    m = MetricasJanela(n_leituras=len(eventos))
    if not eventos:
        return m

    m.delta_acumulado = sum(e.delta for e in eventos)
    m.delta_medio = m.delta_acumulado / len(eventos)
    m.volume_total_janela = sum(e.volume_total for e in eventos)
    precos = [e.preco_fechamento for e in eventos]
    m.amplitude_janela = max(precos) - min(precos) if precos else 0.0
    if eventos[0].preco_abertura:
        m.deslocamento_preco_pct = (
            (eventos[-1].preco_fechamento - eventos[0].preco_abertura)
            / eventos[0].preco_abertura * 100.0)

    tol = janela.config.tolerancia_faixa_pts
    _persistencia_corrente: Dict[float, int] = {}
    _presente_leitura_anterior: Dict[float, bool] = {}
    for e in eventos:
        if not e.book:
            continue
        precos_leitura = set()
        for nivel in e.book.niveis:
            chave = round(nivel.preco / tol) * tol
            precos_leitura.add(chave)
            m.persistencia_nivel[chave] = m.persistencia_nivel.get(chave, 0) + 1
            m.variacao_lote_nivel.setdefault(chave, []).append(
                nivel.qtd_compra + nivel.qtd_venda)
            if _presente_leitura_anterior.get(chave) is False:
                m.reapareceu_no_mesmo_nivel[chave] = m.reapareceu_no_mesmo_nivel.get(chave, 0) + 1
            if nivel.participante_compra:
                m.participantes_recorrentes[nivel.participante_compra] = (
                    m.participantes_recorrentes.get(nivel.participante_compra, 0) + 1)
            if nivel.participante_venda:
                m.participantes_recorrentes[nivel.participante_venda] = (
                    m.participantes_recorrentes.get(nivel.participante_venda, 0) + 1)
        for chave_ant in list(_presente_leitura_anterior.keys()):
            _presente_leitura_anterior[chave_ant] = chave_ant in precos_leitura
        for chave in precos_leitura:
            _presente_leitura_anterior.setdefault(chave, True)

    return m


# =============================================================================
# BLOCO 3 (parte 2) — REGRAS DE DETECCAO
# Assinatura comum: detector(janela, metricas, config) -> SinalDetectado
# =============================================================================

def _confianca_por_score(score: float, config: ConfigMotorFluxo,
                          teto: Optional[NivelConfianca] = None) -> NivelConfianca:
    """Score -> nivel de confianca, respeitando o teto imposto pela
    granularidade do dado (ver docstring do modulo)."""
    if score >= config.limiar_forte:
        nivel = NivelConfianca.INFERENCIA_FORTE
    elif score >= config.limiar_fraco:
        nivel = NivelConfianca.INFERENCIA_FRACA
    else:
        return NivelConfianca.INDEFINIDO
    ordem = [NivelConfianca.INDEFINIDO, NivelConfianca.INFERENCIA_FRACA,
             NivelConfianca.INFERENCIA_FORTE, NivelConfianca.LEITURA_DIRETA]
    if teto and ordem.index(nivel) > ordem.index(teto):
        return teto
    return nivel


def _sinal_indefinido(tipo: str, modo: ModoDados, motivo: str) -> SinalDetectado:
    return SinalDetectado(tipo=tipo, presente=False, direcao=None, score=0.0,
                           confianca=NivelConfianca.INDEFINIDO,
                           evidencias_favor=[], evidencias_contra=[],
                           modo_dados=modo, detalhe=motivo)


def detectar_ordem_escondida(janela: JanelaFluxo, m: MetricasJanela,
                              config: ConfigMotorFluxo) -> SinalDetectado:
    """Combinacao: execucoes repetidas no mesmo nivel + pouco deslocamento +
    volume acima do lote visivel + reaparicao de liquidez no nivel."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("ordem_escondida", modo, "amostras insuficientes")

    candidatos = {p: n for p, n in m.persistencia_nivel.items()
                  if n >= config.min_execucoes_mesmo_nivel}
    if not candidatos:
        return _sinal_indefinido("ordem_escondida", modo, "nenhum nivel com execucoes repetidas suficientes")

    preco_alvo = max(candidatos, key=candidatos.get)
    n_persistencia = candidatos[preco_alvo]
    reaparicoes = m.reapareceu_no_mesmo_nivel.get(preco_alvo, 0)
    serie_lote = m.variacao_lote_nivel.get(preco_alvo, [])
    lote_medio = sum(serie_lote) / len(serie_lote) if serie_lote else 0.0
    deslocou_pouco = abs(m.deslocamento_preco_pct) <= config.deslocamento_max_absorcao_pct

    favor: List[Evidencia] = [
        Evidencia(f"{n_persistencia} leituras seguidas com oferta no nivel {preco_alvo:.2f}",
                   peso=20, fonte_dado="persistencia_nivel"),
    ]
    contra: List[Evidencia] = []
    score = 20.0 * min(n_persistencia / config.min_execucoes_mesmo_nivel, 2.0)

    if reaparicoes > 0:
        favor.append(Evidencia(f"liquidez reapareceu {reaparicoes}x no mesmo nivel",
                                peso=15 * reaparicoes, fonte_dado="reapareceu_no_mesmo_nivel"))
        score += 15 * min(reaparicoes, 3)
    else:
        contra.append(Evidencia("sem reaparicao detectada -- pode ser so oferta parada",
                                 peso=-10, fonte_dado="reapareceu_no_mesmo_nivel"))
        score -= 10

    if deslocou_pouco:
        favor.append(Evidencia(f"preco deslocou so {m.deslocamento_preco_pct:.2f}% na janela",
                                peso=20, fonte_dado="deslocamento_preco_pct"))
        score += 20
    else:
        contra.append(Evidencia("preco deslocou o suficiente para nao sugerir defesa",
                                 peso=-15, fonte_dado="deslocamento_preco_pct"))
        score -= 15

    if lote_medio > 0 and m.volume_total_janela > 0:
        proporcao = m.volume_total_janela / max(lote_medio, 1e-9)
        if proporcao >= 3:
            favor.append(Evidencia(f"volume executado ~{proporcao:.1f}x maior que o lote medio exposto",
                                    peso=25, fonte_dado="volume_total_janela/variacao_lote_nivel"))
            score += 25

    modo_participante = modo == ModoDados.PARTICIPANTE
    participante_recorrente = None
    if modo_participante:
        recorrentes = {p: c for p, c in m.participantes_recorrentes.items() if c >= 2}
        if recorrentes:
            participante_recorrente = max(recorrentes, key=recorrentes.get)
            favor.append(Evidencia(f"participante {participante_recorrente} reaparece defendendo o nivel",
                                    peso=20, fonte_dado="participantes_recorrentes"))
            score += 20

    teto = (config.teto_confianca_sem_participante if not modo_participante
            else NivelConfianca.LEITURA_DIRETA)
    # Sem participante, nunca afirmar com certeza -- capado explicitamente
    # em INFERENCIA_FORTE no maximo (regra 3 do usuario).
    confianca = _confianca_por_score(score, config, teto=teto)
    presente = confianca != NivelConfianca.INDEFINIDO

    if presente:
        rotulo = ("possivel iceberg/ordem escondida" if not modo_participante
                   else f"ordem escondida provavel (participante {participante_recorrente})"
                   if participante_recorrente else "possivel ordem escondida")
    else:
        rotulo = "evidencia insuficiente para ordem escondida"

    return SinalDetectado(tipo="ordem_escondida", presente=presente, direcao=None,
                           score=score, confianca=confianca,
                           evidencias_favor=favor, evidencias_contra=contra,
                           modo_dados=modo, detalhe=rotulo)


def detectar_dominancia_fluxo(janela: JanelaFluxo, m: MetricasJanela,
                               config: ConfigMotorFluxo) -> SinalDetectado:
    """Agregado: agressao liquida + persistencia do delta + aceitacao de
    preco + ausencia de absorcao forte do lado oposto."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("dominancia_fluxo", modo, "amostras insuficientes")

    if m.volume_total_janela <= 0:
        return _sinal_indefinido("dominancia_fluxo", modo, "sem volume na janela")

    delta_pct = m.delta_acumulado / m.volume_total_janela
    direcao = "compra" if delta_pct > 0 else "venda" if delta_pct < 0 else None
    favor: List[Evidencia] = []
    contra: List[Evidencia] = []
    score = 0.0

    if abs(delta_pct) >= config.delta_minimo_dominancia:
        favor.append(Evidencia(f"delta liquido {delta_pct:+.1%} do volume da janela",
                                peso=35, fonte_dado="delta_acumulado"))
        score += 35 * min(abs(delta_pct) / config.delta_minimo_dominancia, 2.0)
    else:
        contra.append(Evidencia(f"delta liquido {delta_pct:+.1%} abaixo do minimo de dominancia",
                                 peso=-20, fonte_dado="delta_acumulado"))
        score -= 20

    eventos = janela.eventos
    sinais_delta_mesma_direcao = sum(
        1 for e in eventos if (e.delta > 0) == (delta_pct > 0) and e.delta != 0)
    continuidade = sinais_delta_mesma_direcao / len(eventos) if eventos else 0
    if continuidade >= 0.7:
        favor.append(Evidencia(f"{continuidade:.0%} das leituras da janela na mesma direcao",
                                peso=25, fonte_dado="serie_delta"))
        score += 25
    elif continuidade <= 0.4:
        contra.append(Evidencia("delta inconsistente entre leituras (sem continuidade)",
                                 peso=-15, fonte_dado="serie_delta"))
        score -= 15

    deslocou_a_favor = (
        (direcao == "compra" and m.deslocamento_preco_pct > 0) or
        (direcao == "venda" and m.deslocamento_preco_pct < 0))
    if deslocou_a_favor:
        favor.append(Evidencia("preco aceitou a direcao do fluxo (deslocamento a favor)",
                                peso=20, fonte_dado="deslocamento_preco_pct"))
        score += 20
    else:
        contra.append(Evidencia("preco nao acompanhou a direcao do fluxo -- possivel absorcao contraria",
                                 peso=-25, fonte_dado="deslocamento_preco_pct"))
        score -= 25

    if modo == ModoDados.PARTICIPANTE and m.participantes_recorrentes:
        top = max(m.participantes_recorrentes.values())
        concentracao = top / max(sum(m.participantes_recorrentes.values()), 1)
        if concentracao >= 0.4:
            favor.append(Evidencia(f"agressao concentrada ({concentracao:.0%}) num numero pequeno de participantes",
                                    peso=20, fonte_dado="participantes_recorrentes"))
            score += 20

    teto = (NivelConfianca.INFERENCIA_FORTE if modo == ModoDados.AGREGADO
            else NivelConfianca.LEITURA_DIRETA)
    confianca = _confianca_por_score(score, config, teto=teto)
    presente = confianca != NivelConfianca.INDEFINIDO and direcao is not None

    return SinalDetectado(
        tipo="dominancia_fluxo", presente=presente, direcao=direcao if presente else None,
        score=score, confianca=confianca, evidencias_favor=favor, evidencias_contra=contra,
        modo_dados=modo,
        detalhe=f"dominancia {direcao}" if presente else "sem dominancia clara")


def detectar_absorcao(janela: JanelaFluxo, m: MetricasJanela,
                       config: ConfigMotorFluxo) -> SinalDetectado:
    """Agressao relevante + pouca progressao de preco + persistencia do
    nivel/faixa -> absorcao (do lado OPOSTO ao agressor)."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("absorcao", modo, "amostras insuficientes")
    if m.volume_total_janela < config.volume_minimo_absorcao:
        return _sinal_indefinido("absorcao", modo, "volume abaixo do minimo para avaliar absorcao")

    delta_pct = (m.delta_acumulado / m.volume_total_janela) if m.volume_total_janela else 0
    lado_agressor = "compra" if delta_pct > 0 else "venda" if delta_pct < 0 else None
    if lado_agressor is None:
        return _sinal_indefinido("absorcao", modo, "sem agressao liquida definida")

    favor: List[Evidencia] = [
        Evidencia(f"volume da janela ({m.volume_total_janela:.0f}) acima do minimo",
                   peso=15, fonte_dado="volume_total_janela"),
        Evidencia(f"agressao liquida {delta_pct:+.1%} a favor de {lado_agressor}",
                   peso=15, fonte_dado="delta_acumulado"),
    ]
    contra: List[Evidencia] = []
    score = 30.0

    pouca_progressao = abs(m.deslocamento_preco_pct) <= config.deslocamento_max_absorcao_pct
    if pouca_progressao:
        favor.append(Evidencia(f"deslocamento de apenas {m.deslocamento_preco_pct:.2f}% apesar da agressao",
                                peso=35, fonte_dado="deslocamento_preco_pct"))
        score += 35
    else:
        contra.append(Evidencia("preco progrediu proporcional a agressao -- nao parece absorcao",
                                 peso=-30, fonte_dado="deslocamento_preco_pct"))
        score -= 30

    niveis_persistentes = sum(1 for n in m.persistencia_nivel.values()
                               if n >= config.persistencia_minima_nivel)
    if niveis_persistentes > 0:
        favor.append(Evidencia(f"{niveis_persistentes} nivel(is) com persistencia >= {config.persistencia_minima_nivel} leituras",
                                peso=20, fonte_dado="persistencia_nivel"))
        score += 20

    # Absorcao classifica o lado que RESISTIU, o oposto de quem agrediu.
    direcao_absorcao = "vendedora" if lado_agressor == "compra" else "compradora"
    teto = (NivelConfianca.INFERENCIA_FORTE if modo == ModoDados.AGREGADO
            else NivelConfianca.LEITURA_DIRETA)
    confianca = _confianca_por_score(score, config, teto=teto)
    presente = confianca != NivelConfianca.INDEFINIDO and pouca_progressao

    return SinalDetectado(
        tipo="absorcao", presente=presente,
        direcao=direcao_absorcao if presente else None,
        score=score, confianca=confianca, evidencias_favor=favor, evidencias_contra=contra,
        modo_dados=modo,
        detalhe=f"absorcao {direcao_absorcao}" if presente else "sem absorcao clara")


def detectar_reposicao_lote(janela: JanelaFluxo, m: MetricasJanela,
                             config: ConfigMotorFluxo) -> SinalDetectado:
    """Liquidez some (executada), reaparece repetidamente no mesmo
    preco/faixa. Sinal fundamentalmente FINO -- teto de confianca baixo em
    modo agregado com cadencia de minutos (ver docstring do modulo)."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("reposicao_lote", modo, "amostras insuficientes")

    candidatos = {p: n for p, n in m.reapareceu_no_mesmo_nivel.items()
                  if n >= config.reaparicoes_min_reposicao}
    if not candidatos:
        return _sinal_indefinido("reposicao_lote", modo, "nenhuma reaparicao repetida detectada")

    preco_alvo = max(candidatos, key=candidatos.get)
    n_reaparicoes = candidatos[preco_alvo]
    favor = [Evidencia(f"nivel {preco_alvo:.2f} reabastecido {n_reaparicoes}x na janela",
                        peso=30 * n_reaparicoes, fonte_dado="reapareceu_no_mesmo_nivel")]
    score = 30.0 * min(n_reaparicoes, 3)
    contra: List[Evidencia] = []

    # Teto DELIBERADAMENTE baixo: com leitura a cada 5 min, "reposicao de
    # lote" e indistinguivel de "ordens novas independentes chegando por
    # acaso no mesmo preco redondo" sem tick a tick.
    confianca = _confianca_por_score(score, config, teto=config.teto_confianca_sinais_finos_agregado)
    presente = confianca != NivelConfianca.INDEFINIDO

    return SinalDetectado(tipo="reposicao_lote", presente=presente, direcao=None,
                           score=score, confianca=confianca,
                           evidencias_favor=favor, evidencias_contra=contra,
                           modo_dados=modo,
                           detalhe=f"possivel reposicao em {preco_alvo:.2f}" if presente else "sem padrao de reposicao")


def detectar_retirada_liquidez(janela: JanelaFluxo, m: MetricasJanela,
                                config: ConfigMotorFluxo) -> SinalDetectado:
    """Reducao rapida do lote exposto ANTES do deslocamento. Precisa
    comparar 2 leituras consecutivas -- com cadencia de minutos, so pega
    retiradas que duram minutos, nao a retirada de ultimo instante que
    tipicamente precede um movimento rapido de verdade."""
    modo = janela.modo
    eventos = janela.eventos
    if len(eventos) < 2:
        return _sinal_indefinido("retirada_liquidez", modo, "menos de 2 leituras na janela")

    quedas: List[Tuple[float, float]] = []  # (preco, queda_pct)
    for preco, serie in m.variacao_lote_nivel.items():
        if len(serie) < 2:
            continue
        anterior, atual = serie[-2], serie[-1]
        if anterior > 0 and atual < anterior * 0.5:
            quedas.append((preco, 1 - atual / anterior))

    if not quedas:
        return _sinal_indefinido("retirada_liquidez", modo, "nenhuma queda relevante de lote exposto")

    preco_alvo, queda_pct = max(quedas, key=lambda t: t[1])
    favor = [Evidencia(f"lote exposto em {preco_alvo:.2f} caiu {queda_pct:.0%} entre leituras",
                        peso=40, fonte_dado="variacao_lote_nivel")]
    score = 40.0
    contra: List[Evidencia] = []

    deslocamento_seguinte = eventos[-1].preco_fechamento - eventos[-2].preco_fechamento
    precedeu_movimento = abs(deslocamento_seguinte) > 0
    if precedeu_movimento:
        favor.append(Evidencia("esvaziamento seguido de deslocamento de preco na leitura seguinte",
                                peso=30, fonte_dado="preco_fechamento"))
        score += 30
    else:
        contra.append(Evidencia("esvaziamento sem deslocamento subsequente -- pode ser ruido",
                                 peso=-20, fonte_dado="preco_fechamento"))
        score -= 20

    confianca = _confianca_por_score(score, config, teto=config.teto_confianca_sinais_finos_agregado)
    presente = confianca != NivelConfianca.INDEFINIDO
    direcao = None
    if presente and deslocamento_seguinte != 0:
        direcao = "venda" if deslocamento_seguinte < 0 else "compra"

    return SinalDetectado(tipo="retirada_liquidez", presente=presente, direcao=direcao,
                           score=score, confianca=confianca,
                           evidencias_favor=favor, evidencias_contra=contra,
                           modo_dados=modo,
                           detalhe=f"possivel retirada em {preco_alvo:.2f}" if presente else "sem retirada relevante")


def detectar_empilhamento(janela: JanelaFluxo, m: MetricasJanela,
                           config: ConfigMotorFluxo) -> SinalDetectado:
    """Aumento progressivo de liquidez num nivel ao longo da janela."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("empilhamento", modo, "amostras insuficientes")

    candidatos = []
    for preco, serie in m.variacao_lote_nivel.items():
        if len(serie) < 3:
            continue
        crescente = all(b >= a for a, b in zip(serie, serie[1:]))
        crescimento_pct = (serie[-1] - serie[0]) / serie[0] if serie[0] > 0 else 0
        if crescente and crescimento_pct > 0.3:
            candidatos.append((preco, crescimento_pct, serie))

    if not candidatos:
        return _sinal_indefinido("empilhamento", modo, "nenhum nivel com crescimento sustentado de liquidez")

    preco_alvo, crescimento_pct, serie = max(candidatos, key=lambda t: t[1])
    favor = [Evidencia(f"liquidez em {preco_alvo:.2f} cresceu {crescimento_pct:.0%} de forma sustentada",
                        peso=35, fonte_dado="variacao_lote_nivel")]
    score = 35.0 + 10.0 * min(len(serie) - 3, 3)
    contra: List[Evidencia] = []

    eventos = janela.eventos
    preco_atual = eventos[-1].preco_fechamento if eventos else 0
    lado = "compra" if preco_alvo < preco_atual else "venda" if preco_alvo > preco_atual else None

    confianca = _confianca_por_score(score, config, teto=NivelConfianca.INFERENCIA_FORTE)
    presente = confianca != NivelConfianca.INDEFINIDO

    return SinalDetectado(tipo="empilhamento", presente=presente, direcao=lado,
                           score=score, confianca=confianca,
                           evidencias_favor=favor, evidencias_contra=contra,
                           modo_dados=modo,
                           detalhe=(f"empilhamento de {lado} em {preco_alvo:.2f}"
                                    if presente else "sem empilhamento claro"))


def detectar_rompimento(janela: JanelaFluxo, m: MetricasJanela,
                         config: ConfigMotorFluxo,
                         faixa_referencia: Optional[Tuple[float, float]] = None
                         ) -> Tuple[SinalDetectado, SinalDetectado]:
    """Retorna (rompimento_com_aceitacao, rompimento_falso) -- mutuamente
    exclusivos na pratica, mas calculados juntos porque comparam a MESMA
    janela contra a MESMA faixa de referencia."""
    modo = janela.modo
    eventos = janela.eventos
    if len(eventos) < config.aceitacao_min_leituras_fora_faixa + 1:
        indef = _sinal_indefinido("rompimento_aceitacao", modo, "amostras insuficientes")
        indef2 = _sinal_indefinido("rompimento_falso", modo, "amostras insuficientes")
        return indef, indef2

    if faixa_referencia is None:
        precos_ref = [e.preco_fechamento for e in eventos[:-config.aceitacao_min_leituras_fora_faixa]]
        if not precos_ref:
            precos_ref = [eventos[0].preco_abertura]
        faixa_referencia = (min(precos_ref), max(precos_ref))

    minimo_ref, maximo_ref = faixa_referencia
    ultimos = eventos[-config.aceitacao_min_leituras_fora_faixa:]
    rompeu_cima = all(e.preco_fechamento > maximo_ref for e in ultimos)
    rompeu_baixo = all(e.preco_fechamento < minimo_ref for e in ultimos)

    if not (rompeu_cima or rompeu_baixo):
        # Checa rompimento falso: chegou a romper mas voltou.
        maximo_janela = max(e.maxima for e in eventos)
        minimo_janela = min(e.minima for e in eventos)
        preco_atual = eventos[-1].preco_fechamento
        rompeu_e_voltou_cima = (maximo_janela > maximo_ref and
                                 (preco_atual - maximo_ref) <= config.retorno_max_pts_rompimento_falso)
        rompeu_e_voltou_baixo = (minimo_janela < minimo_ref and
                                  (minimo_ref - preco_atual) <= config.retorno_max_pts_rompimento_falso)
        if rompeu_e_voltou_cima or rompeu_e_voltou_baixo:
            direcao_falsa = "compra" if rompeu_e_voltou_cima else "venda"
            favor = [Evidencia(f"rompimento de {direcao_falsa} sem sustentacao -- voltou pra faixa anterior",
                                peso=50, fonte_dado="maxima/minima da janela")]
            score = 50.0
            confianca = _confianca_por_score(score, config, teto=NivelConfianca.INFERENCIA_FORTE)
            falso = SinalDetectado(tipo="rompimento_falso", presente=confianca != NivelConfianca.INDEFINIDO,
                                    direcao=direcao_falsa, score=score, confianca=confianca,
                                    evidencias_favor=favor, evidencias_contra=[], modo_dados=modo,
                                    detalhe=f"rompimento falso de {direcao_falsa}")
            return _sinal_indefinido("rompimento_aceitacao", modo, "sem rompimento sustentado"), falso
        return (_sinal_indefinido("rompimento_aceitacao", modo, "preco dentro da faixa de referencia"),
                _sinal_indefinido("rompimento_falso", modo, "sem rompimento detectado"))

    direcao = "compra" if rompeu_cima else "venda"
    favor = [Evidencia(
        f"{config.aceitacao_min_leituras_fora_faixa} leituras seguidas fora da faixa "
        f"[{minimo_ref:.2f}, {maximo_ref:.2f}]", peso=40, fonte_dado="preco_fechamento")]
    score = 40.0
    contra: List[Evidencia] = []

    if m.volume_total_janela >= config.volume_minimo_absorcao:
        favor.append(Evidencia("volume da janela sustenta a continuidade", peso=25,
                                fonte_dado="volume_total_janela"))
        score += 25
    else:
        contra.append(Evidencia("volume abaixo do esperado para confirmar aceitacao", peso=-15,
                                 fonte_dado="volume_total_janela"))
        score -= 15

    confianca = _confianca_por_score(score, config, teto=NivelConfianca.INFERENCIA_FORTE)
    presente = confianca != NivelConfianca.INDEFINIDO
    aceitacao = SinalDetectado(tipo="rompimento_aceitacao", presente=presente, direcao=direcao,
                                score=score, confianca=confianca,
                                evidencias_favor=favor, evidencias_contra=contra, modo_dados=modo,
                                detalhe=f"rompimento com aceitacao de {direcao}" if presente else "aceitacao nao confirmada")
    return aceitacao, _sinal_indefinido("rompimento_falso", modo, "rompimento em curso, ainda nao invalidado")


def detectar_agressao(janela: JanelaFluxo, m: MetricasJanela,
                       config: ConfigMotorFluxo) -> Tuple[SinalDetectado, SinalDetectado]:
    """Agressao compradora / vendedora -- leitura quase direta, ja que
    agressao_compradora_pct/vendedora_pct vem calculada por leitura (igual
    a hoje em calcular_pressao_fluxo / SaldoAgressaoPct)."""
    modo = janela.modo
    eventos = janela.eventos
    if not eventos:
        return (_sinal_indefinido("agressao_compradora", modo, "sem leituras"),
                _sinal_indefinido("agressao_vendedora", modo, "sem leituras"))

    ultimo = eventos[-1]
    resultado = []
    for tipo, pct, direcao in (("agressao_compradora", ultimo.agressao_compradora_pct, "compra"),
                                ("agressao_vendedora", ultimo.agressao_vendedora_pct, "venda")):
        if pct <= 0:
            resultado.append(_sinal_indefinido(tipo, modo, "percentual de agressao nao capturado"))
            continue
        presente = pct >= 55.0
        score = pct
        favor = [Evidencia(f"{pct:.0f}% de agressao {direcao} nesta leitura", peso=pct,
                            fonte_dado="agressao_compradora_pct/agressao_vendedora_pct")]
        # Isso e leitura quase direta da fonte (ja vem calculado por
        # leitura) -- nao precisa de inferencia sobre janela.
        confianca = (NivelConfianca.LEITURA_DIRETA if presente and pct >= 65
                     else NivelConfianca.INFERENCIA_FRACA if presente
                     else NivelConfianca.INDEFINIDO)
        resultado.append(SinalDetectado(tipo=tipo, presente=presente, direcao=direcao if presente else None,
                                         score=score, confianca=confianca,
                                         evidencias_favor=favor, evidencias_contra=[], modo_dados=modo,
                                         detalhe=f"{pct:.0f}% agressao {direcao}"))
    return resultado[0], resultado[1]


def detectar_desequilibrio_execucao(janela: JanelaFluxo, m: MetricasJanela,
                                     config: ConfigMotorFluxo) -> SinalDetectado:
    """Desequilibrio simples entre volume executado a favor de compra vs
    venda na janela -- distinto de dominancia (que exige continuidade e
    aceitacao de preco); aqui e so o desbalanco bruto."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("desequilibrio_execucao", modo, "amostras insuficientes")
    if m.volume_total_janela <= 0:
        return _sinal_indefinido("desequilibrio_execucao", modo, "sem volume na janela")

    delta_pct = m.delta_acumulado / m.volume_total_janela
    if abs(delta_pct) < 0.10:
        return _sinal_indefinido("desequilibrio_execucao", modo, "volumes equilibrados")

    direcao = "compra" if delta_pct > 0 else "venda"
    score = min(abs(delta_pct) * 100, 100)
    favor = [Evidencia(f"execucao desequilibrada {delta_pct:+.1%} para {direcao}", peso=score,
                        fonte_dado="delta_acumulado/volume_total_janela")]
    confianca = _confianca_por_score(score, config, teto=NivelConfianca.INFERENCIA_FORTE)
    presente = confianca != NivelConfianca.INDEFINIDO

    return SinalDetectado(tipo="desequilibrio_execucao", presente=presente,
                           direcao=direcao if presente else None, score=score, confianca=confianca,
                           evidencias_favor=favor, evidencias_contra=[], modo_dados=modo,
                           detalhe=f"desequilibrio para {direcao}" if presente else "sem desequilibrio relevante")


def detectar_defesa_preco(janela: JanelaFluxo, m: MetricasJanela,
                           config: ConfigMotorFluxo) -> SinalDetectado:
    """Nivel que resiste a testes repetidos (preco toca e nao rompe),
    combinando persistencia de nivel com ausencia de deslocamento."""
    modo = janela.modo
    if not janela.tem_amostras_suficientes():
        return _sinal_indefinido("defesa_preco", modo, "amostras insuficientes")

    candidatos = {p: n for p, n in m.persistencia_nivel.items()
                  if n >= config.persistencia_minima_nivel}
    if not candidatos:
        return _sinal_indefinido("defesa_preco", modo, "nenhum nivel testado repetidamente")

    preco_alvo = max(candidatos, key=candidatos.get)
    n_testes = candidatos[preco_alvo]
    eventos = janela.eventos
    tocou_e_nao_rompeu = all(
        (not e.book or e.book.nivel(preco_alvo, config.tolerancia_faixa_pts) is not None)
        for e in eventos)

    score = 25.0 * min(n_testes / config.persistencia_minima_nivel, 3.0)
    favor = [Evidencia(f"nivel {preco_alvo:.2f} testado {n_testes}x sem rompimento", peso=score,
                        fonte_dado="persistencia_nivel")]
    contra: List[Evidencia] = []
    if not tocou_e_nao_rompeu:
        contra.append(Evidencia("nivel deixou de aparecer em alguma leitura -- defesa pode ter cedido",
                                 peso=-20, fonte_dado="book.nivel"))
        score -= 20

    preco_atual = eventos[-1].preco_fechamento if eventos else 0
    lado = "compra" if preco_alvo < preco_atual else "venda" if preco_alvo > preco_atual else None
    confianca = _confianca_por_score(score, config, teto=NivelConfianca.INFERENCIA_FORTE)
    presente = confianca != NivelConfianca.INDEFINIDO

    return SinalDetectado(tipo="defesa_preco", presente=presente, direcao=lado,
                           score=score, confianca=confianca,
                           evidencias_favor=favor, evidencias_contra=contra, modo_dados=modo,
                           detalhe=f"defesa de {lado} em {preco_alvo:.2f}" if presente else "sem defesa clara")


# =============================================================================
# BLOCO 6 (parte 2) — ORQUESTRACAO
# =============================================================================

DetectorSimples = Callable[[JanelaFluxo, MetricasJanela, ConfigMotorFluxo], SinalDetectado]

DETECTORES_SIMPLES: Dict[str, DetectorSimples] = {
    "ordem_escondida": detectar_ordem_escondida,
    "dominancia_fluxo": detectar_dominancia_fluxo,
    "absorcao": detectar_absorcao,
    "reposicao_lote": detectar_reposicao_lote,
    "retirada_liquidez": detectar_retirada_liquidez,
    "empilhamento": detectar_empilhamento,
    "desequilibrio_execucao": detectar_desequilibrio_execucao,
    "defesa_preco": detectar_defesa_preco,
}


class MotorFluxoMicroestrutura:
    """Ponto de entrada unico. Uso tipico:

        motor = MotorFluxoMicroestrutura(ConfigMotorFluxo.conservador())
        motor.ingerir(evento_agregado)   # 1x por leitura/ciclo
        classificacao = motor.classificar()
    """

    def __init__(self, config: Optional[ConfigMotorFluxo] = None):
        self.config = config or ConfigMotorFluxo.conservador()
        self.janela = JanelaFluxo(self.config)

    def ingerir(self, evento: EventoFluxoAgregado) -> None:
        self.janela.adicionar(evento)

    def classificar(self) -> ClassificacaoFluxo:
        m = calcular_metricas(self.janela)
        sinais: Dict[str, SinalDetectado] = {
            nome: fn(self.janela, m, self.config)
            for nome, fn in DETECTORES_SIMPLES.items()
        }
        aceitacao, falso = detectar_rompimento(self.janela, m, self.config)
        sinais["rompimento_aceitacao"] = aceitacao
        sinais["rompimento_falso"] = falso
        agr_compra, agr_venda = detectar_agressao(self.janela, m, self.config)
        sinais["agressao_compradora"] = agr_compra
        sinais["agressao_vendedora"] = agr_venda

        eventos = self.janela.eventos
        ts = eventos[-1].timestamp if eventos else datetime.now()
        ativos = [s for s in sinais.values() if s.presente]
        resumo = ("sem sinais de fluxo com confianca suficiente" if not ativos else
                  " · ".join(f"{s.tipo}({s.confianca.value})" for s in ativos))

        return ClassificacaoFluxo(timestamp=ts, modo_dados=self.janela.modo,
                                   sinais=sinais, resumo=resumo)


# =============================================================================
# ADAPTADOR — a partir dos dados JA existentes no app (agentes_info/dados_tela)
# =============================================================================

def evento_a_partir_da_leitura_atual(
        dados_tela: dict, agentes_info: dict, fluxo_calculado: dict) -> EventoFluxoAgregado:
    """Constroi um EventoFluxoAgregado a partir do que ja existe hoje:
    dados_tela (leitura de tela/IA), agentes_info (ofertantes_compra/venda,
    cada oferta com "preco"/"qtde"/"agente"), fluxo_calculado (saida de
    calcular_pressao_fluxo: "agressao_pct" 0-100 e "delta_agressao"). Nao
    inventa nenhum campo -- so remapeia o que ja e coletado.

    NUNCA assume nome de corretora: quando o campo "agente" vem ausente OU
    com o rotulo generico "BOOK" (o que o prompt de visao manda escrever
    quando NAO ha nome legivel -- ver extrair_dados_tela), trata como
    participante desconhecido e mantem ModoDados.AGREGADO."""
    niveis: List[NivelBook] = []
    participante_presente = False
    for lado, chave in (("compra", "ofertantes_compra"), ("venda", "ofertantes_venda")):
        for oferta in (agentes_info or {}).get(chave, []) or []:
            _agente_bruto = str(oferta.get("agente", "") or "").strip()
            nome = _agente_bruto if _agente_bruto and _agente_bruto.upper() != "BOOK" else None
            if nome:
                participante_presente = True
            niveis.append(NivelBook(
                preco=float(oferta.get("preco", 0) or 0),
                qtd_compra=float(oferta.get("qtde", 0) or 0) if lado == "compra" else 0.0,
                qtd_venda=float(oferta.get("qtde", 0) or 0) if lado == "venda" else 0.0,
                participante_compra=nome if lado == "compra" else None,
                participante_venda=nome if lado == "venda" else None,
            ))

    modo = ModoDados.PARTICIPANTE if participante_presente else ModoDados.AGREGADO
    book = BookSnapshot(timestamp=datetime.now(), niveis=niveis, modo=modo,
                         fonte="visao_ia_profit",
                         preco_referencia=float(dados_tela.get("preco_atual", 0) or 0))

    preco_atual = float(dados_tela.get("preco_atual", 0) or 0)
    # calcular_pressao_fluxo devolve um UNICO "agressao_pct" (0-100, onde
    # >50 = mais pressao compradora) -- nao dois campos separados. O
    # complemento (100 - pct) e a leitura do lado vendedor, nao um campo
    # que precisa vir de outro lugar.
    _agressao_pct = float((fluxo_calculado or {}).get("agressao_pct", 50.0) or 50.0)
    return EventoFluxoAgregado(
        timestamp=datetime.now(),
        preco_abertura=float(dados_tela.get("abertura", preco_atual) or preco_atual),
        preco_fechamento=preco_atual,
        maxima=float(dados_tela.get("maxima", preco_atual) or preco_atual),
        minima=float(dados_tela.get("minima", preco_atual) or preco_atual),
        volume_total=float(dados_tela.get("volume", 0) or 0),
        agressao_compradora_pct=_agressao_pct,
        agressao_vendedora_pct=100.0 - _agressao_pct,
        delta=float((fluxo_calculado or {}).get("delta_agressao", 0) or 0),
        book=book,
    )
