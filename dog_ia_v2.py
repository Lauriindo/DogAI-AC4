import argparse
import heapq
import math
import random
from array import array
from collections import deque

import pygame

LARGURA, ALTURA = 1050, 680
FPS = 60
AREA_MAPA_LARGURA = LARGURA - 260

BRANCO = (245, 245, 245)
PRETO = (20, 22, 28)
ASFALTO = (42, 45, 52)
CALÇADA_CLARA = (130, 134, 142)
MEIO_FIO = (175, 180, 188)
PISO_TATIL = (235, 190, 20)
GRAMA = (46, 115, 65)
COR_EDIFICACAO = (120, 92, 70)

CORPO_ROBO = (30, 136, 229)
DETALHE_ROBO = (15, 76, 129)
CABECA_ROBO = (230, 236, 245)
ARNES_GUIA = (255, 215, 0)
VERDE_LIVRE = (46, 204, 113)
LARANJA_ALERTA = (255, 140, 0)
VERMELHO_PERIGO = (225, 55, 55)
ROXO_SUSPENSO = (155, 89, 182)
CIANO_ROTA = (0, 200, 255)
CORES_CARROS = [(52, 152, 219), (236, 240, 241), (149, 165, 166), (39, 174, 96), (241, 196, 15)]
COR_INFRATOR = (192, 57, 43)

RUA_Y = 250
RUA_ALTURA = 170
FAIXA_X = 580
FAIXA_LARGURA = 95
FAIXA_X_MIN = FAIXA_X + 30
FAIXA_X_MAX = FAIXA_X + FAIXA_LARGURA - 30
FAIXA_RECT = pygame.Rect(FAIXA_X, RUA_Y, FAIXA_LARGURA, RUA_ALTURA)

RAIO_ROBO = 20
VEL_ROBO = 156.0
GIRO_MAX = 4.0
GUIA = 42
FOLGA_GUIA = 10
RAIO_TUTOR = 12
VEL_TUTOR = 150.0

CELULA = 10
INFLA_SOLO = 30
INFLA_EDIFICACAO = 22
INFLA_SUSPENSO = 38
MARGEM_PAREDE = 35
CUSTO_TATIL = 0.45
TEMPO_REPLANEJAR = 3.5

ALCANCE_LIDAR = 165
SIGMA_LIDAR = 1.5
TAXA_DROPOUT = 0.02
JANELA_MEDIANA = 3
HORIZONTE_PREDICAO = 1.0
HORIZONTE_TRAVESSIA = 2.0

VEL_CARRO = 190.0
ACEL = 110.0
DESACEL = 280.0
DIST_SEGUIMENTO = 22
PROB_INFRATOR = 0.12
COMPRIMENTO_CARRO = 48
LARGURA_CARRO = 26

FASES = [
	("VERDE", 7.0),
	("AMARELO", 2.0),
	("TODOS_VERM_1", 1.5),
	("PEDESTRE", 8.0),
	("TODOS_VERM_2", 1.5),
]
LIMITE_TRAVESSIA = (RUA_ALTURA + 24 + GUIA) / VEL_ROBO * 1.35 + 0.4
LIMITE_VIAGEM = 120.0

PISOS_TATEIS = [
	pygame.Rect(40, 120, 595, 14),
	pygame.Rect(621, 120, 14, 130),
	pygame.Rect(621, RUA_Y + RUA_ALTURA, 14, 130),
	pygame.Rect(150, 536, 485, 14),
]

DESTINOS = {
	"1": ("Mercado", (160, 543)),
	"2": ("Farmácia", (715, 560)),
	"3": ("Padaria", (715, 130)),
	"4": ("Casa", (95, 127)),
}


def rotacionar_ponto(cx, cy, px, py, angulo):
	s = math.sin(angulo)
	c = math.cos(angulo)
	dx = px - cx
	dy = py - cy
	return (int(cx + dx * c - dy * s), int(cy + dx * s + dy * c))


def normalizar_angulo(a):
	return (a + math.pi) % (2 * math.pi) - math.pi


def em_rua(y):
	return RUA_Y < y < RUA_Y + RUA_ALTURA


def lado_da_rua(y):
	return "norte" if y < RUA_Y + RUA_ALTURA / 2 else "sul"


def distancia_meio_fio(y):
	if y <= RUA_Y:
		return RUA_Y - y
	if y >= RUA_Y + RUA_ALTURA:
		return y - (RUA_Y + RUA_ALTURA)
	return 0.0


def aplicar_barreira(x0, y0, x1, y1, autorizado):
	"""Impede descer o meio-fio fora da faixa ou sem autorização de travessia."""
	if not em_rua(y1):
		return x1, y1
	if em_rua(y0):
		return min(max(x1, FAIXA_X + 6), FAIXA_X + FAIXA_LARGURA - 6), y1
	if autorizado and FAIXA_X + 6 <= x1 <= FAIXA_X + FAIXA_LARGURA - 6:
		return x1, y1
	return x1, (RUA_Y if y0 <= RUA_Y else RUA_Y + RUA_ALTURA)


def distancia_ponto_rect(px, py, rect):
	cx = min(max(px, rect.left), rect.right)
	cy = min(max(py, rect.top), rect.bottom)
	return math.hypot(px - cx, py - cy)


def fator_tensao(tensao):
	if tensao <= FOLGA_GUIA:
		return 1.0
	return max(0.15, 1.0 - (tensao - FOLGA_GUIA) / 20.0)


class Semaforo:
	def __init__(self):
		self.indice = 0
		self.tempo_fase = 0.0

	@property
	def fase(self):
		return FASES[self.indice][0]

	@property
	def tempo_restante(self):
		return FASES[self.indice][1] - self.tempo_fase

	def atualizar(self, dt):
		self.tempo_fase += dt
		while self.tempo_fase >= FASES[self.indice][1]:
			self.tempo_fase -= FASES[self.indice][1]
			self.indice = (self.indice + 1) % len(FASES)


class Veiculo:
	def __init__(self, direcao, infrator):
		self.direcao = direcao
		self.infrator = infrator
		self.v_max = VEL_CARRO * random.uniform(0.8, 1.0)
		self.v = self.v_max
		self.a = 0.0
		self.comprometido = False
		self.y = RUA_Y + 128 if direcao == 1 else RUA_Y + 42
		self.x = -COMPRIMENTO_CARRO if direcao == 1 else AREA_MAPA_LARGURA + COMPRIMENTO_CARRO
		self.cor = COR_INFRATOR if infrator else random.choice(CORES_CARROS)

	@property
	def frente(self):
		return self.x + self.direcao * COMPRIMENTO_CARRO / 2

	@property
	def traseira(self):
		return self.x - self.direcao * COMPRIMENTO_CARRO / 2

	@property
	def linha_retencao(self):
		return FAIXA_X - 10 if self.direcao == 1 else FAIXA_X + FAIXA_LARGURA + 10

	def rect(self):
		return pygame.Rect(round(self.x - COMPRIMENTO_CARRO / 2), round(self.y - LARGURA_CARRO / 2), COMPRIMENTO_CARRO, LARGURA_CARRO)

	def atualizar(self, dt, semaforo, lider):
		espaco = float("inf")
		if lider is not None:
			espaco = (lider.traseira - self.frente) * self.direcao - DIST_SEGUIMENTO
		dist_linha = (self.linha_retencao - self.frente) * self.direcao
		if dist_linha > -2 and not self.infrator:
			fase = semaforo.fase
			if fase == "VERDE":
				self.comprometido = False
			elif fase == "AMARELO" and not self.comprometido and dist_linha < self.v ** 2 / (2 * DESACEL):
				self.comprometido = True
			if fase != "VERDE" and not self.comprometido:
				espaco = min(espaco, max(dist_linha, 0.0))
		v_alvo = min(self.v_max, math.sqrt(2 * DESACEL * 0.35 * max(espaco, 0.0)))
		v_antiga = self.v
		if self.v < v_alvo:
			self.v = min(v_alvo, self.v + ACEL * dt)
		else:
			self.v = max(v_alvo, self.v - DESACEL * dt)
		self.a = (self.v - v_antiga) / dt
		self.x += self.direcao * self.v * dt

	def deslocamento_previsto(self, horizonte):
		if self.a < -1.0:
			t_parada = self.v / -self.a
			if t_parada < horizonte:
				return self.v * t_parada / 2
		return max(0.0, self.v * horizonte + 0.5 * self.a * horizonte ** 2)

	def zona_varrida(self, horizonte=HORIZONTE_PREDICAO):
		atual = self.rect()
		futuro = atual.move(round(self.direcao * self.deslocamento_previsto(horizonte)), 0)
		return atual.union(futuro)


class PlanejadorAStar:
	VIZINHOS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]

	def __init__(self):
		self.colunas = AREA_MAPA_LARGURA // CELULA
		self.linhas = ALTURA // CELULA
		self.custos = []

	def construir_grade(self, obstaculos):
		margens = {"solo": INFLA_SOLO, "edificacao": INFLA_EDIFICACAO, "suspenso": INFLA_SUSPENSO}
		infladas = []
		for obs in obstaculos:
			m = margens.get(obs["tipo"])
			if m is not None:
				infladas.append(obs["rect"].inflate(2 * m, 2 * m))
		self.custos = []
		for j in range(self.linhas):
			linha = []
			cy = j * CELULA + CELULA // 2
			for i in range(self.colunas):
				cx = i * CELULA + CELULA // 2
				linha.append(self.custo_celula(cx, cy, infladas))
			self.custos.append(linha)

	def custo_celula(self, cx, cy, infladas):
		if cx < MARGEM_PAREDE or cx > AREA_MAPA_LARGURA - MARGEM_PAREDE or cy < MARGEM_PAREDE or cy > ALTURA - MARGEM_PAREDE:
			return None
		if RUA_Y - 10 <= cy <= RUA_Y + RUA_ALTURA + 10 and not (FAIXA_X_MIN <= cx <= FAIXA_X_MAX):
			return None
		for r in infladas:
			if r.collidepoint(cx, cy):
				return None
		for p in PISOS_TATEIS:
			if p.collidepoint(cx, cy):
				return CUSTO_TATIL
		return 1.0

	def celula(self, ponto):
		i = min(max(int(ponto[0] // CELULA), 0), self.colunas - 1)
		j = min(max(int(ponto[1] // CELULA), 0), self.linhas - 1)
		return (i, j)

	def livre(self, c):
		return 0 <= c[0] < self.colunas and 0 <= c[1] < self.linhas and self.custos[c[1]][c[0]] is not None

	def celula_livre_mais_proxima(self, c):
		if self.livre(c):
			return c
		visitados = {c}
		fila = deque([c])
		while fila:
			atual = fila.popleft()
			for di, dj in self.VIZINHOS:
				v = (atual[0] + di, atual[1] + dj)
				if v in visitados or not (0 <= v[0] < self.colunas and 0 <= v[1] < self.linhas):
					continue
				if self.livre(v):
					return v
				visitados.add(v)
				fila.append(v)
		return None

	@staticmethod
	def heuristica(a, b):
		dx = abs(a[0] - b[0])
		dy = abs(a[1] - b[1])
		return ((max(dx, dy) - min(dx, dy)) + math.sqrt(2) * min(dx, dy)) * CUSTO_TATIL

	def planejar(self, inicio, fim, obstaculos):
		self.construir_grade(obstaculos)
		s = self.celula_livre_mais_proxima(self.celula(inicio))
		g = self.celula_livre_mais_proxima(self.celula(fim))
		if s is None or g is None:
			return []
		abertos = [(0.0, 0, s)]
		custo_g = {s: 0.0}
		pai = {s: None}
		contador = 0
		fechados = set()
		while abertos:
			_, _, atual = heapq.heappop(abertos)
			if atual == g:
				break
			if atual in fechados:
				continue
			fechados.add(atual)
			for di, dj in self.VIZINHOS:
				viz = (atual[0] + di, atual[1] + dj)
				if not self.livre(viz):
					continue
				if di and dj and (not self.livre((viz[0], atual[1])) or not self.livre((atual[0], viz[1]))):
					continue
				passo = (math.sqrt(2) if di and dj else 1.0) * self.custos[viz[1]][viz[0]]
				novo = custo_g[atual] + passo
				if novo < custo_g.get(viz, float("inf")):
					custo_g[viz] = novo
					pai[viz] = atual
					contador += 1
					heapq.heappush(abertos, (novo + self.heuristica(viz, g), contador, viz))
		if g not in pai:
			return []
		caminho = []
		c = g
		while c is not None:
			caminho.append((c[0] * CELULA + CELULA // 2, c[1] * CELULA + CELULA // 2))
			c = pai[c]
		caminho.reverse()
		caminho[-1] = (fim[0], fim[1])
		return caminho


class RoboCaoGuia:
	def __init__(self, x, y):
		self.x = x
		self.y = y
		self.angulo = 0.0
		self.raio = RAIO_ROBO
		self.alcance_lidar = ALCANCE_LIDAR
		self.num_raios = 19
		self.fov = math.radians(150)
		self.historico = [deque(maxlen=JANELA_MEDIANA) for _ in range(self.num_raios)]
		self.leituras_lidar = []
		self.status_assistivo = "Escolha um destino (teclas 1 a 4)."
		self.cor_alerta = VERDE_LIVRE
		self.passo_animacao = 0.0
		self.velocidade = 0.0

	def ler_lidar(self, obstaculos):
		"""LiDAR com clipline, ruído gaussiano, dropout e mediana temporal."""
		self.leituras_lidar = []
		angulo_inicial = self.angulo - self.fov / 2
		passo_angulo = self.fov / (self.num_raios - 1)
		origem = (round(self.x), round(self.y))
		for i in range(self.num_raios):
			ang = angulo_inicial + i * passo_angulo
			fim = (round(self.x + math.cos(ang) * self.alcance_lidar), round(self.y + math.sin(ang) * self.alcance_lidar))
			dist = float(self.alcance_lidar)
			tipo = None
			for obs in obstaculos:
				corte = obs["rect"].clipline(origem, fim)
				if corte:
					d = min(math.hypot(p[0] - self.x, p[1] - self.y) for p in corte)
					if d < dist:
						dist = d
						tipo = obs["tipo"]
			if random.random() < TAXA_DROPOUT:
				dist = float(self.alcance_lidar)
				tipo = None
			else:
				dist = min(float(self.alcance_lidar), max(0.0, dist + random.gauss(0, SIGMA_LIDAR)))
			self.historico[i].append((dist, tipo))
			amostras = sorted(self.historico[i], key=lambda a: a[0])
			mediana = amostras[len(amostras) // 2]
			self.leituras_lidar.append({"angulo": ang, "distancia": mediana[0], "tipo": mediana[1]})

	def setores(self):
		dists = [l["distancia"] if l["tipo"] != "veiculo" else self.alcance_lidar for l in self.leituras_lidar]
		terco = self.num_raios // 3
		return min(dists[:terco]), min(dists[terco:2 * terco]), min(dists[2 * terco:])

	def suspenso_a_frente(self):
		terco = self.num_raios // 3
		return any(l["tipo"] == "suspenso" and l["distancia"] < 115 for l in self.leituras_lidar[terco:2 * terco])

	def mover(self, angulo_desejado, velocidade, dt, autorizado):
		diff = normalizar_angulo(angulo_desejado - self.angulo)
		self.angulo = normalizar_angulo(self.angulo + max(-GIRO_MAX * dt, min(GIRO_MAX * dt, diff)))
		nx = self.x + math.cos(self.angulo) * velocidade * dt
		ny = self.y + math.sin(self.angulo) * velocidade * dt
		self.x, self.y = aplicar_barreira(self.x, self.y, nx, ny, autorizado)
		self.velocidade = velocidade
		self.passo_animacao += velocidade * dt * 0.15

	def desenhar(self, tela, tutor):
		for r in self.leituras_lidar:
			fim_x = self.x + math.cos(r["angulo"]) * r["distancia"]
			fim_y = self.y + math.sin(r["angulo"]) * r["distancia"]
			cor_raio = VERDE_LIVRE if r["distancia"] >= self.alcance_lidar - 5 else VERMELHO_PERIGO
			pygame.draw.line(tela, cor_raio, (self.x, self.y), (fim_x, fim_y), 1)
			if r["tipo"]:
				pygame.draw.circle(tela, BRANCO, (int(fim_x), int(fim_y)), 3)

		cor_arnes = ARNES_GUIA if tutor.tensao <= FOLGA_GUIA else VERMELHO_PERIGO
		pygame.draw.line(tela, cor_arnes, (self.x, self.y), (tutor.x, tutor.y), 4)
		pygame.draw.circle(tela, (235, 235, 240), (int(tutor.x), int(tutor.y)), RAIO_TUTOR)
		pygame.draw.circle(tela, PRETO, (int(tutor.x), int(tutor.y)), RAIO_TUTOR, 2)

		balanco = math.sin(self.passo_animacao) * 5
		offsets_patas = [(10 + balanco, -14), (10 - balanco, 14), (-12 - balanco, -14), (-12 + balanco, 14)]
		for ox, oy in offsets_patas:
			px, py = rotacionar_ponto(self.x, self.y, self.x + ox, self.y + oy, self.angulo)
			pygame.draw.circle(tela, DETALHE_ROBO, (px, py), 5)

		pontos_corpo = [
			rotacionar_ponto(self.x, self.y, self.x + 16, self.y - 11, self.angulo),
			rotacionar_ponto(self.x, self.y, self.x + 16, self.y + 11, self.angulo),
			rotacionar_ponto(self.x, self.y, self.x - 18, self.y + 11, self.angulo),
			rotacionar_ponto(self.x, self.y, self.x - 18, self.y - 11, self.angulo),
		]
		pygame.draw.polygon(tela, CORPO_ROBO, pontos_corpo)
		pygame.draw.polygon(tela, BRANCO, pontos_corpo, 2)

		cab_x, cab_y = rotacionar_ponto(self.x, self.y, self.x + 21, self.y, self.angulo)
		pygame.draw.circle(tela, CABECA_ROBO, (cab_x, cab_y), 9)
		pygame.draw.circle(tela, DETALHE_ROBO, (cab_x, cab_y), 9, 2)
		pygame.draw.circle(tela, DETALHE_ROBO, rotacionar_ponto(self.x, self.y, self.x + 19, self.y - 10, self.angulo), 4)
		pygame.draw.circle(tela, DETALHE_ROBO, rotacionar_ponto(self.x, self.y, self.x + 19, self.y + 10, self.angulo), 4)
		pygame.draw.circle(tela, LARANJA_ALERTA, rotacionar_ponto(self.x, self.y, self.x + 3, self.y, self.angulo), 5)


class Tutor:
	"""Pessoa guiada: entidade independente presa ao robô pelo arnês."""

	def __init__(self, x, y):
		self.x = x
		self.y = y
		self.tensao = 0.0

	def atualizar(self, robo, dt, autorizado):
		dx = robo.x - self.x
		dy = robo.y - self.y
		d = math.hypot(dx, dy)
		if d > GUIA:
			passo = min(VEL_TUTOR * dt, d - GUIA)
			nx = self.x + dx / d * passo
			ny = self.y + dy / d * passo
			self.x, self.y = aplicar_barreira(self.x, self.y, nx, ny, autorizado)
		self.tensao = math.hypot(robo.x - self.x, robo.y - self.y) - GUIA

	def rect(self):
		return pygame.Rect(round(self.x - RAIO_TUTOR), round(self.y - RAIO_TUTOR), 2 * RAIO_TUTOR, 2 * RAIO_TUTOR)


class AudioEstereo:
	def __init__(self):
		self.ativo = False
		self.espera = 0.0
		try:
			pygame.mixer.init(22050, -16, 2, 512)
			self.sons = {"alto": self.gerar_bipe(1046), "medio": self.gerar_bipe(660)}
			self.ativo = True
		except pygame.error:
			self.sons = {}

	@staticmethod
	def gerar_bipe(freq, duracao=0.12, taxa=22050):
		n = int(taxa * duracao)
		amostras = array("h")
		for i in range(n):
			envelope = min(1.0, i / 200, (n - i) / 200)
			v = int(9000 * envelope * math.sin(2 * math.pi * freq * i / taxa))
			amostras.append(v)
			amostras.append(v)
		return pygame.mixer.Sound(buffer=amostras)

	def atualizar(self, dt):
		self.espera = max(0.0, self.espera - dt)

	def tocar(self, tipo, pan):
		if not self.ativo or self.espera > 0:
			return
		angulo = (pan + 1) * math.pi / 4
		canal = self.sons[tipo].play()
		if canal:
			canal.set_volume(math.cos(angulo), math.sin(angulo))
		self.espera = 0.7


def criar_cenario():
	return [
		{"rect": pygame.Rect(230, 85, 45, 75), "tipo": "solo", "nome": "Banca / Hidrante"},
		{"rect": pygame.Rect(460, 160, 32, 32), "tipo": "solo", "nome": "Poste de Luz"},
		{"rect": pygame.Rect(380, 460, 40, 40), "tipo": "solo", "nome": "Lixeira Urbana"},
		{"rect": pygame.Rect(350, 75, 85, 65), "tipo": "suspenso", "nome": "Copa de Árvore"},
		{"rect": pygame.Rect(520, 485, 95, 65), "tipo": "suspenso", "nome": "Toldo de Loja"},
		{"rect": pygame.Rect(25, 35, 110, 55), "tipo": "edificacao", "nome": "Casa"},
		{"rect": pygame.Rect(660, 35, 110, 55), "tipo": "edificacao", "nome": "Padaria"},
		{"rect": pygame.Rect(30, 590, 140, 55), "tipo": "edificacao", "nome": "Mercado"},
		{"rect": pygame.Rect(660, 590, 110, 55), "tipo": "edificacao", "nome": "Farmácia"},
	]


def criar_paredes():
	return [
		{"rect": pygame.Rect(0, 0, AREA_MAPA_LARGURA, 15), "tipo": "parede"},
		{"rect": pygame.Rect(0, ALTURA - 15, AREA_MAPA_LARGURA, 15), "tipo": "parede"},
		{"rect": pygame.Rect(0, 0, 15, ALTURA), "tipo": "parede"},
		{"rect": pygame.Rect(AREA_MAPA_LARGURA - 15, 0, 15, ALTURA), "tipo": "parede"},
	]


class Simulacao:
	def __init__(self, audio=None):
		self.obstaculos = criar_cenario()
		self.paredes = criar_paredes()
		self.semaforo = Semaforo()
		self.veiculos = []
		self.espera_spawn = {1: random.uniform(0.5, 2.0), -1: random.uniform(0.5, 2.0)}
		casa = DESTINOS["4"][1]
		self.robo = RoboCaoGuia(*casa)
		self.tutor = Tutor(casa[0] - GUIA, casa[1])
		self.planejador = PlanejadorAStar()
		self.audio = audio
		self.modo_autonomo = True
		self.estado = "PARADO"
		self.destino_nome = "-"
		self.alvo = None
		self.rota = []
		self.tempo = 0.0
		self.tempo_desvio = 0.0
		self.lado_origem = None
		self.veiculo_risco = None
		self.inicio_viagem = 0.0
		self.ultima_viagem = 0.0
		self.historico_estados = []
		self.colidindo = False
		self.quase = False
		self.alerta_vermelho = False
		self.metricas = {
			"distancia": 0.0,
			"alertas_vermelhos": 0,
			"freios_emergencia": 0,
			"viagens_concluidas": 0,
			"colisoes": 0,
			"quase_colisoes": 0,
			"replanejamentos": 0,
			"tempos_viagem": [],
		}

	def set_estado(self, novo, motivo):
		if novo == self.estado:
			return
		self.historico_estados.append((round(self.tempo, 2), self.estado, novo, motivo))
		if novo == "FREIO_EMERGENCIA":
			self.metricas["freios_emergencia"] += 1
		self.estado = novo

	def definir_destino(self, chave):
		nome, ponto = DESTINOS[chave]
		self.iniciar_viagem(nome, ponto)

	def iniciar_viagem(self, nome, ponto):
		self.destino_nome = nome
		self.alvo = ponto
		self.rota = self.planejador.planejar((self.robo.x, self.robo.y), ponto, self.obstaculos)
		self.inicio_viagem = self.tempo
		self.tempo_desvio = 0.0
		self.lado_origem = None
		if not self.rota:
			self.robo.status_assistivo = "Rota impossível para o destino."
			self.set_estado("PARADO", "A* não encontrou rota")
			return
		self.set_estado("SEGUINDO_ROTA", f"destino {nome} selecionado e rota A* gerada")

	def replanejar(self):
		if self.alvo is None:
			return
		nova = self.planejador.planejar((self.robo.x, self.robo.y), self.alvo, self.obstaculos)
		if nova:
			self.rota = nova
		self.metricas["replanejamentos"] += 1

	def atualizar_trafego(self, dt):
		for direcao in (1, -1):
			faixa = sorted((v for v in self.veiculos if v.direcao == direcao), key=lambda v: v.x * direcao, reverse=True)
			lider = None
			for v in faixa:
				v.atualizar(dt, self.semaforo, lider)
				lider = v
			self.espera_spawn[direcao] -= dt
			if self.espera_spawn[direcao] <= 0:
				novo = Veiculo(direcao, random.random() < PROB_INFRATOR)
				ultimo = faixa[-1] if faixa else None
				if ultimo is None or (ultimo.traseira - novo.frente) * direcao > 40:
					if ultimo is not None:
						novo.v = min(novo.v, ultimo.v)
					self.veiculos.append(novo)
					self.espera_spawn[direcao] = random.uniform(1.5, 4.0)
		self.veiculos = [v for v in self.veiculos if -80 < v.x < AREA_MAPA_LARGURA + 80]

	def obstaculos_sensor(self):
		return self.obstaculos + self.paredes + [{"rect": v.rect(), "tipo": "veiculo"} for v in self.veiculos]

	def risco_veicular(self):
		"""Zona varrida: retângulo futuro de cada veículo em movimento (Δt = 1 s)."""
		r = self.robo
		area_robo = pygame.Rect(round(r.x - r.raio - 6), round(r.y - r.raio - 6), 2 * r.raio + 12, 2 * r.raio + 12)
		area_tutor = self.tutor.rect()
		for v in self.veiculos:
			if v.v > 1:
				zona = v.zona_varrida()
				if zona.colliderect(area_robo) or zona.colliderect(area_tutor):
					return v
		return None

	def pode_atravessar(self):
		if self.semaforo.fase != "PEDESTRE" or self.semaforo.tempo_restante <= LIMITE_TRAVESSIA:
			return False
		return not any(v.v > 1 and v.zona_varrida(HORIZONTE_TRAVESSIA).colliderect(FAIXA_RECT) for v in self.veiculos)

	def proximo_ponto(self):
		r = self.robo
		while len(self.rota) > 1:
			d0 = math.hypot(self.rota[0][0] - r.x, self.rota[0][1] - r.y)
			d1 = math.hypot(self.rota[1][0] - r.x, self.rota[1][1] - r.y)
			if d0 < 16 or d1 <= d0:
				self.rota.pop(0)
			else:
				break
		for p in self.rota[:4]:
			if math.hypot(p[0] - r.x, p[1] - r.y) >= 26:
				return p
		return self.rota[min(3, len(self.rota) - 1)]

	def decidir(self, dt):
		r = self.robo
		dist_alvo = math.hypot(self.alvo[0] - r.x, self.alvo[1] - r.y)
		if dist_alvo < 18:
			self.set_estado("DESTINO_ALCANCADO", "distância ao destino < 18 px")
			r.velocidade = 0.0
			r.cor_alerta = VERDE_LIVRE
			r.status_assistivo = f"DESTINO ALCANÇADO: {self.destino_nome}!"
			self.metricas["viagens_concluidas"] += 1
			self.ultima_viagem = self.tempo - self.inicio_viagem
			self.metricas["tempos_viagem"].append(self.ultima_viagem)
			return

		self.veiculo_risco = self.risco_veicular()
		if self.veiculo_risco is not None:
			self.set_estado("FREIO_EMERGENCIA", "zona varrida de veículo intercepta robô/tutor")
			r.velocidade = 0.0
			r.cor_alerta = VERMELHO_PERIGO
			r.status_assistivo = "FREIO DE EMERGÊNCIA: veículo em rota de colisão!"
			return
		if self.estado == "FREIO_EMERGENCIA":
			self.set_estado("ATRAVESSANDO" if self.lado_origem else "SEGUINDO_ROTA", "zona varrida livre")

		alvo_local = self.proximo_ponto()

		if self.estado == "ATRAVESSANDO" and not em_rua(r.y) and not em_rua(self.tutor.y) and lado_da_rua(r.y) != self.lado_origem:
			self.lado_origem = None
			self.set_estado("SEGUINDO_ROTA", "robô e tutor chegaram à calçada oposta")

		if self.estado != "ATRAVESSANDO" and not em_rua(r.y) and em_rua(alvo_local[1]) and distancia_meio_fio(r.y) < 26:
			if self.pode_atravessar():
				self.lado_origem = lado_da_rua(r.y)
				self.set_estado("ATRAVESSANDO", "fase PEDESTRE com tempo restante suficiente")
			else:
				self.set_estado("AGUARDANDO_SINAL", "chegou ao meio-fio sem autorização de travessia")
				r.velocidade = 0.0
				r.cor_alerta = LARANJA_ALERTA
				r.status_assistivo = f"Aguardando sinal ({self.semaforo.fase}). Pare no meio-fio."
				return

		esq, cen, dire = r.setores()
		fator = fator_tensao(self.tutor.tensao)
		ang_rota = math.atan2(alvo_local[1] - r.y, alvo_local[0] - r.x)

		if self.estado != "ATRAVESSANDO" and cen < 42:
			self.set_estado("DESVIO_LOCAL", "obstáculo a menos de 42 px à frente")
			self.tempo_desvio += dt
			r.cor_alerta = VERMELHO_PERIGO
			if r.suspenso_a_frente():
				r.status_assistivo = "ALERTA CABEÇA: Galho/Toldo baixo! Desviando..."
			else:
				r.status_assistivo = "OBSTÁCULO NA CALÇADA: Contornando..."
			angulo = r.angulo + (-1.2 if esq > dire else 1.2)
			vel = VEL_ROBO * 0.3 * fator
			if self.tempo_desvio > TEMPO_REPLANEJAR:
				self.replanejar()
				self.tempo_desvio = 0.0
		else:
			if self.estado == "DESVIO_LOCAL":
				self.set_estado("SEGUINDO_ROTA", "frente livre novamente")
			self.tempo_desvio = 0.0
			angulo = ang_rota
			if esq < 24:
				angulo += 0.5
				r.cor_alerta = LARANJA_ALERTA
				r.status_assistivo = "Obstáculo à esquerda. Deslocando à direita."
			elif dire < 24:
				angulo -= 0.5
				r.cor_alerta = LARANJA_ALERTA
				r.status_assistivo = "Obstáculo à direita. Deslocando à esquerda."
			elif fator < 1.0:
				r.cor_alerta = LARANJA_ALERTA
				r.status_assistivo = "Tutor ficando para trás. Reduzindo velocidade."
			else:
				r.cor_alerta = VERDE_LIVRE
				if self.estado == "ATRAVESSANDO":
					r.status_assistivo = "Atravessando na faixa com sinal aberto."
				else:
					r.status_assistivo = f"Seguindo rota A* até {self.destino_nome}."
			diff = normalizar_angulo(angulo - r.angulo)
			vel = VEL_ROBO * fator * max(0.25, math.cos(diff))
			vel *= min(1.0, max(0.35, dist_alvo / 50))

		r.mover(angulo, vel, dt, self.estado == "ATRAVESSANDO")

	def controle_manual(self, dt, teclas):
		r = self.robo
		r.status_assistivo = "Modo manual (setas)."
		r.cor_alerta = VERDE_LIVRE
		if not teclas:
			return
		if teclas["esq"]:
			r.angulo -= 3.0 * dt
		if teclas["dir"]:
			r.angulo += 3.0 * dt
		vel = 180.0 if teclas["frente"] else 0.0
		r.mover(r.angulo, vel, dt, self.semaforo.fase == "PEDESTRE")

	def verificar_seguranca(self):
		r = self.robo
		t = self.tutor
		colidindo = False
		quase = False
		for v in self.veiculos:
			rect = v.rect()
			folga = min(distancia_ponto_rect(r.x, r.y, rect) - r.raio, distancia_ponto_rect(t.x, t.y, rect) - RAIO_TUTOR)
			if folga <= 0:
				colidindo = True
			elif folga < 20:
				quase = True
		for obs in self.obstaculos:
			if obs["tipo"] in ("solo", "edificacao") and distancia_ponto_rect(r.x, r.y, obs["rect"]) < r.raio - 4:
				colidindo = True
			if obs["tipo"] == "suspenso" and distancia_ponto_rect(t.x, t.y, obs["rect"]) < RAIO_TUTOR - 2:
				colidindo = True
		if colidindo and not self.colidindo:
			self.metricas["colisoes"] += 1
		if quase and not colidindo and not self.quase:
			self.metricas["quase_colisoes"] += 1
		self.colidindo = colidindo
		self.quase = quase and not colidindo
		vermelho = r.cor_alerta == VERMELHO_PERIGO
		if vermelho and not self.alerta_vermelho:
			self.metricas["alertas_vermelhos"] += 1
		self.alerta_vermelho = vermelho

	def atualizar_audio(self, dt):
		if self.audio is None:
			return
		self.audio.atualizar(dt)
		r = self.robo
		if self.estado == "FREIO_EMERGENCIA" and self.veiculo_risco is not None:
			rel = normalizar_angulo(math.atan2(self.veiculo_risco.y - r.y, self.veiculo_risco.x - r.x) - r.angulo)
			self.audio.tocar("alto", max(-1.0, min(1.0, rel / (math.pi / 2))))
			return
		candidatas = [l for l in r.leituras_lidar if l["tipo"] not in (None, "parede")]
		if not candidatas:
			return
		perto = min(candidatas, key=lambda l: l["distancia"])
		if perto["distancia"] < 60:
			rel = normalizar_angulo(perto["angulo"] - r.angulo)
			pan = max(-1.0, min(1.0, rel / (r.fov / 2)))
			self.audio.tocar("alto" if perto["distancia"] < 42 else "medio", pan)

	def passo(self, dt, teclas=None):
		self.tempo += dt
		self.semaforo.atualizar(dt)
		self.atualizar_trafego(dt)
		self.robo.ler_lidar(self.obstaculos_sensor())
		x0, y0 = self.robo.x, self.robo.y
		if not self.modo_autonomo:
			self.controle_manual(dt, teclas)
		elif self.estado not in ("PARADO", "DESTINO_ALCANCADO"):
			self.decidir(dt)
		self.metricas["distancia"] += math.hypot(self.robo.x - x0, self.robo.y - y0)
		if self.modo_autonomo:
			autorizado = self.estado == "ATRAVESSANDO" or em_rua(self.robo.y)
		else:
			autorizado = self.semaforo.fase == "PEDESTRE"
		self.tutor.atualizar(self.robo, dt, autorizado)
		self.verificar_seguranca()
		self.atualizar_audio(dt)


def desenhar_ambiente_urbano(tela):
	tela.fill(CALÇADA_CLARA)
	pygame.draw.rect(tela, GRAMA, (0, 0, AREA_MAPA_LARGURA, 28))
	pygame.draw.rect(tela, GRAMA, (0, ALTURA - 28, AREA_MAPA_LARGURA, 28))
	pygame.draw.rect(tela, ASFALTO, (0, RUA_Y, AREA_MAPA_LARGURA, RUA_ALTURA))
	pygame.draw.line(tela, MEIO_FIO, (0, RUA_Y), (AREA_MAPA_LARGURA, RUA_Y), 4)
	pygame.draw.line(tela, MEIO_FIO, (0, RUA_Y + RUA_ALTURA), (AREA_MAPA_LARGURA, RUA_Y + RUA_ALTURA), 4)
	for x in range(15, AREA_MAPA_LARGURA - 20, 45):
		if not (FAIXA_X - 10 <= x <= FAIXA_X + FAIXA_LARGURA + 5):
			pygame.draw.line(tela, BRANCO, (x, RUA_Y + RUA_ALTURA // 2), (x + 22, RUA_Y + RUA_ALTURA // 2), 3)
	for y in range(RUA_Y + 12, RUA_Y + RUA_ALTURA - 12, 22):
		pygame.draw.rect(tela, BRANCO, (FAIXA_X, y, FAIXA_LARGURA, 12))
	pygame.draw.line(tela, BRANCO, (FAIXA_X - 10, RUA_Y + 90), (FAIXA_X - 10, RUA_Y + RUA_ALTURA - 4), 3)
	pygame.draw.line(tela, BRANCO, (FAIXA_X + FAIXA_LARGURA + 10, RUA_Y + 4), (FAIXA_X + FAIXA_LARGURA + 10, RUA_Y + 80), 3)
	for p in PISOS_TATEIS:
		pygame.draw.rect(tela, PISO_TATIL, p)


def desenhar_semaforos(tela, semaforo):
	fase = semaforo.fase
	cores = [(231, 76, 60), (241, 196, 15), (46, 204, 113)]
	acesa = {"VERDE": 2, "AMARELO": 1}.get(fase, 0)
	for x, y in ((FAIXA_X + FAIXA_LARGURA + 18, RUA_Y - 62), (FAIXA_X - 34, RUA_Y + RUA_ALTURA + 10)):
		pygame.draw.rect(tela, PRETO, (x, y, 16, 46), border_radius=4)
		for k, cor in enumerate(cores):
			pygame.draw.circle(tela, cor if k == acesa else (60, 60, 60), (x + 8, y + 8 + k * 15), 5)
	cor_ped = (46, 204, 113) if fase == "PEDESTRE" else (231, 76, 60)
	for x, y in ((FAIXA_X - 26, RUA_Y - 34), (FAIXA_X + FAIXA_LARGURA + 8, RUA_Y + RUA_ALTURA + 8)):
		pygame.draw.rect(tela, PRETO, (x, y, 18, 26), border_radius=3)
		pygame.draw.rect(tela, cor_ped, (x + 4, y + 4, 10, 18), border_radius=2)


def desenhar_cena(tela, sim, fontes):
	fonte_titulo, fonte_texto, fonte_pequena = fontes
	desenhar_ambiente_urbano(tela)
	desenhar_semaforos(tela, sim.semaforo)

	for obs in sim.obstaculos:
		rect = obs["rect"]
		if obs["tipo"] == "suspenso":
			pygame.draw.rect(tela, (90, 95, 102), rect.move(5, 5), border_radius=12)
			pygame.draw.rect(tela, ROXO_SUSPENSO, rect, border_radius=12)
			pygame.draw.rect(tela, BRANCO, rect, 2, border_radius=12)
			rotulo = "ALTO"
		elif obs["tipo"] == "edificacao":
			pygame.draw.rect(tela, COR_EDIFICACAO, rect, border_radius=4)
			pygame.draw.rect(tela, BRANCO, rect, 2, border_radius=4)
			rotulo = obs["nome"].upper()
		else:
			pygame.draw.rect(tela, (70, 74, 82), rect, border_radius=5)
			pygame.draw.rect(tela, BRANCO, rect, 2, border_radius=5)
			rotulo = "SOLO"
		lbl = fonte_pequena.render(rotulo, True, BRANCO)
		tela.blit(lbl, (rect.centerx - lbl.get_width() // 2, rect.centery - 7))

	for chave, (nome, p) in DESTINOS.items():
		pygame.draw.circle(tela, PRETO, p, 9, 2)
		lbl = fonte_pequena.render(chave, True, PRETO)
		tela.blit(lbl, (p[0] - lbl.get_width() // 2, p[1] - 7))

	if sim.rota:
		pygame.draw.lines(tela, CIANO_ROTA, False, [(sim.robo.x, sim.robo.y)] + sim.rota, 2)
	if sim.alvo:
		pygame.draw.circle(tela, VERDE_LIVRE, sim.alvo, 20, 3)
		pygame.draw.circle(tela, VERDE_LIVRE, sim.alvo, 7)

	for v in sim.veiculos:
		if v.v > 1:
			pygame.draw.rect(tela, (255, 130, 130), v.zona_varrida(), 1)
		rect = v.rect()
		pygame.draw.rect(tela, v.cor, rect, border_radius=6)
		para_brisa = rect.inflate(-30, -8).move(v.direcao * 8, 0)
		pygame.draw.rect(tela, (40, 50, 70), para_brisa, border_radius=3)
		if v.infrator:
			pygame.draw.rect(tela, (255, 255, 0), rect, 2, border_radius=6)

	sim.robo.desenhar(tela, sim.tutor)

	painel_x = AREA_MAPA_LARGURA
	pygame.draw.rect(tela, PRETO, (painel_x, 0, LARGURA - painel_x, ALTURA))
	pygame.draw.line(tela, BRANCO, (painel_x, 0), (painel_x, ALTURA), 2)
	x = painel_x + 15
	y = 15
	tela.blit(fonte_titulo.render("TELEMETRIA DOG-IA V2", True, CORPO_ROBO), (x, y))
	y += 34
	sem = sim.semaforo
	min_dist = min(l["distancia"] for l in sim.robo.leituras_lidar) if sim.robo.leituras_lidar else 0
	linhas = [
		f"Modo: {'AUTÔNOMO (IA)' if sim.modo_autonomo else 'MANUAL (Setas)'}",
		f"Estado: {sim.estado}",
		f"Semáforo: {sem.fase} ({sem.tempo_restante:.1f}s)",
		f"Destino: {sim.destino_nome}",
		f"LiDAR (mediana): {min_dist:.0f} px",
		f"Tensão do arnês: {sim.tutor.tensao:.1f} px",
	]
	for texto in linhas:
		tela.blit(fonte_texto.render(texto, True, BRANCO), (x, y))
		y += 22
	y += 6
	pygame.draw.rect(tela, sim.robo.cor_alerta, (x, y, 230, 70), border_radius=8)
	palavras = sim.robo.status_assistivo.split(" ")
	linha_atual = ""
	y_alerta = y + 8
	for p in palavras:
		if len(linha_atual + p) < 27:
			linha_atual += p + " "
		else:
			tela.blit(fonte_texto.render(linha_atual, True, PRETO), (x + 8, y_alerta))
			y_alerta += 19
			linha_atual = p + " "
	tela.blit(fonte_texto.render(linha_atual, True, PRETO), (x + 8, y_alerta))
	y += 84

	m = sim.metricas
	em_viagem = sim.estado not in ("PARADO", "DESTINO_ALCANCADO")
	tempo_viagem = sim.tempo - sim.inicio_viagem if em_viagem else sim.ultima_viagem
	metricas = [
		("MÉTRICAS DA VIAGEM", CORPO_ROBO),
		(f"Tempo: {tempo_viagem:.1f} s", BRANCO),
		(f"Distância total: {m['distancia']:.0f} px", BRANCO),
		(f"Alertas vermelhos: {m['alertas_vermelhos']}", BRANCO),
		(f"Freios de emergência: {m['freios_emergencia']}", BRANCO),
		(f"Viagens concluídas: {m['viagens_concluidas']}", BRANCO),
		(f"Colisões: {m['colisoes']}  Quase: {m['quase_colisoes']}", BRANCO),
		("", BRANCO),
		("CONTROLES", CORPO_ROBO),
		("1 Mercado  2 Farmácia", BRANCO),
		("3 Padaria  4 Casa", BRANCO),
		("Clique Esq: destino livre", BRANCO),
		("Clique Dir: criar obstáculo", BRANCO),
		("ESPAÇO: Manual / IA", BRANCO),
		("R: Reiniciar", BRANCO),
	]
	for texto, cor in metricas:
		tela.blit(fonte_texto.render(texto, True, cor), (x, y))
		y += 22


def executar_benchmark(n, seed):
	if seed is not None:
		random.seed(seed)
	sim = Simulacao()
	dt = 1.0 / FPS
	for _ in range(int(5 / dt)):
		sim.passo(dt)
	sequencia = ["1", "2", "3", "4"]
	sucessos = 0
	tempos = []
	for i in range(n):
		colisoes_antes = sim.metricas["colisoes"]
		sim.definir_destino(sequencia[i % len(sequencia)])
		t0 = sim.tempo
		while sim.estado != "DESTINO_ALCANCADO" and sim.tempo - t0 < LIMITE_VIAGEM:
			sim.passo(dt)
		if sim.estado == "DESTINO_ALCANCADO":
			tempos.append(sim.tempo - t0)
			if sim.metricas["colisoes"] == colisoes_antes:
				sucessos += 1
	m = sim.metricas
	media = sum(tempos) / len(tempos) if tempos else 0.0
	print(f"=== BENCHMARK DOG-IA V2 | viagens={n} | seed={seed} ===")
	print(f"Taxa de sucesso: {100 * sucessos / n:.1f}% ({sucessos}/{n})")
	print(f"Tempo médio por viagem: {media:.2f} s")
	print(f"Distância percorrida: {m['distancia']:.0f} px")
	print(f"Colisões: {m['colisoes']}")
	print(f"Quase-colisões: {m['quase_colisoes']}")
	print(f"Alertas vermelhos: {m['alertas_vermelhos']}")
	print(f"Freios de emergência: {m['freios_emergencia']}")
	print(f"Replanejamentos: {m['replanejamentos']}")
	print(f"Viagens concluídas: {m['viagens_concluidas']}")
	return sim


def main():
	parser = argparse.ArgumentParser(description="DOG-IA V2 - Simulador urbano de cão-guia autônomo")
	parser.add_argument("--benchmark", type=int, default=None, help="executa N viagens sem interface gráfica")
	parser.add_argument("--seed", type=int, default=None, help="semente aleatória para reprodutibilidade")
	args = parser.parse_args()

	if args.benchmark:
		executar_benchmark(args.benchmark, args.seed)
		return
	if args.seed is not None:
		random.seed(args.seed)

	pygame.init()
	tela = pygame.display.set_mode((LARGURA, ALTURA))
	pygame.display.set_caption("DOG-IA V2 — Simulador Urbano de Cão-Guia Autônomo")
	clock = pygame.time.Clock()
	fontes = (
		pygame.font.SysFont("arial", 20, bold=True),
		pygame.font.SysFont("arial", 15),
		pygame.font.SysFont("arial", 12, bold=True),
	)
	audio = AudioEstereo()
	sim = Simulacao(audio)

	rodando = True
	while rodando:
		dt = min(clock.tick(FPS) / 1000.0, 0.05)
		for evento in pygame.event.get():
			if evento.type == pygame.QUIT:
				rodando = False
			elif evento.type == pygame.MOUSEBUTTONDOWN:
				mx, my = pygame.mouse.get_pos()
				if mx < AREA_MAPA_LARGURA:
					if evento.button == 1:
						sim.iniciar_viagem("Ponto clicado", (mx, my))
					elif evento.button == 3:
						sim.obstaculos.append({
							"rect": pygame.Rect(mx - 22, my - 22, 44, 44),
							"tipo": random.choice(["solo", "suspenso"]),
							"nome": "Obstáculo",
						})
			elif evento.type == pygame.KEYDOWN:
				if evento.key == pygame.K_SPACE:
					sim.modo_autonomo = not sim.modo_autonomo
				elif evento.key == pygame.K_r:
					sim = Simulacao(audio)
				elif evento.unicode in DESTINOS:
					sim.definir_destino(evento.unicode)

		teclas = pygame.key.get_pressed()
		sim.passo(dt, {"esq": teclas[pygame.K_LEFT], "dir": teclas[pygame.K_RIGHT], "frente": teclas[pygame.K_UP]})
		desenhar_cena(tela, sim, fontes)
		pygame.display.flip()

	pygame.quit()


if __name__ == "__main__":
	main()
