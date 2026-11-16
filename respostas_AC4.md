# AC-4 — Projeto DOG-IA V2: Respostas das Questões

Código entregue: `dog_ia_v2.py` (evolução da `dog_ia_sim_V1.py` com os Marcos 1 a 4).

Execução interativa: `python dog_ia_v2.py` (teclas 1 a 4 escolhem o destino).
Execução headless: `python dog_ia_v2.py --benchmark 20 --seed 1`

---

## 1. Arquitetura Híbrida de Navegação

**1 - Qual limitação da navegação puramente reativa é resolvida e por que o planejador global sozinho não basta?**

A navegação puramente reativa só olha a leitura atual do LiDAR e a direção do alvo, então cai em mínimos locais: diante de um obstáculo em "U", ou de uma sequência de obstáculos entre o robô e o destino, ela fica girando ou oscilando sem nunca chegar. Ela também não sabe que precisa ir até a faixa de pedestres nem consegue preferir o piso tátil. O A* resolve isso porque enxerga o mapa inteiro, encontra um caminho que contorna os obstáculos (com a inflação do C-Space) e passa pela faixa, preferindo o piso tátil por ter custo menor.

Por outro lado, o A* sozinho não basta porque ele planeja sobre um mapa estático: não vê carros em movimento, obstáculos novos colocados depois do planejamento, nem o ruído do sensor. Em ambiente urbano tudo isso muda o tempo todo, então a camada reativa (desvio local com LiDAR, freio de emergência por zona varrida e espera do semáforo) é o que garante a segurança em tempo real. Quando o desvio local dura mais de 3,5 s, o sistema replaneja com o A*, juntando as duas camadas.

---

## 2. Máquina de Estados

Viagem executada: tecla 1 (Casa → Mercado), seed 1.

**1 - Estados em ordem e condição de cada transição:**

| Tempo (s) | Transição | Condição |
|---|---|---|
| 5,00 | PARADO → SEGUINDO_ROTA | destino Mercado selecionado e rota A* gerada |
| 8,48 | SEGUINDO_ROTA → AGUARDANDO_SINAL | chegou ao meio-fio (< 26 px) e o próximo ponto da rota está na rua, mas o sinal de pedestre não estava aberto |
| 10,52 | AGUARDANDO_SINAL → ATRAVESSANDO | fase PEDESTRE, tempo restante > 2,44 s e nenhuma zona varrida de veículo sobre a faixa |
| 11,75 | ATRAVESSANDO → FREIO_EMERGENCIA | a zona varrida (1 s) de um veículo interceptou o robô/tutor |
| 11,78 | FREIO_EMERGENCIA → ATRAVESSANDO | zona varrida livre novamente |
| 12,33 | ATRAVESSANDO → SEGUINDO_ROTA | robô e tutor chegaram à calçada oposta |
| 15,28 | SEGUINDO_ROTA → DESTINO_ALCANCADO | distância ao destino < 18 px |

O freio nesse trecho foi bem curto (0,03 s): um carro ainda em velocidade constante antes de começar a frear para o sinal vermelho fez a predição projetar o retângulo dele sobre o robô. É um comportamento conservador da predição. Em outras viagens também pode aparecer DESVIO_LOCAL, quando há obstáculo a menos de 42 px à frente.

**2 - Diferença entre AGUARDANDO_SINAL e FREIO_EMERGENCIA:**

AGUARDANDO_SINAL é uma parada planejada e normal: o robô está na calçada, no meio-fio, esperando a fase PEDESTRE com tempo suficiente para atravessar. Ela depende da regra de trânsito (semáforo) e acontece em toda travessia.

FREIO_EMERGENCIA é uma parada reativa de segurança: acontece em qualquer ponto (inclusive no meio da rua) quando a predição por zona varrida mostra que um veículo vai atingir o robô ou o tutor no próximo 1 s, independente da cor do semáforo. Ela serve justamente para casos anormais, como um carro infrator furando o vermelho.

---

## 3. Percepção e Ruído do Sensor

**1 - Por que a mediana é melhor que a média para falhas do tipo "leitura = alcance máximo"?**

O dropout gera um valor extremo (outlier), por exemplo 165 px quando o real é 40 px. Na média esse valor puxa o resultado para cima: (40 + 40 + 165) / 3 ≈ 82 px, ou seja, o robô "enxergaria" o obstáculo bem mais longe do que ele está, o que é perigoso. Na mediana o outlier vai para a ponta da lista ordenada e é descartado: mediana(40, 40, 165) = 40 px. Como a falha é rara (2%), quase nunca há duas falhas seguidas na janela, então a mediana elimina a leitura fantasma sem distorcer a distância.

**2 - Custo do filtro em atraso, com 60 varreduras por segundo:**

Com janela de 3, a mediana só muda quando pelo menos 2 das 3 leituras mudam. Quando um obstáculo aparece, a primeira leitura nova é "voto vencido" e só na segunda varredura a mediana passa a mostrar o obstáculo. O atraso é de 1 varredura, ou seja, 1/60 ≈ 0,017 s (no pior caso, cerca de 2 varreduras, aproximadamente 0,033 s). A 156 px/s, isso equivale a só 2,6 a 5,2 px de deslocamento do robô, um custo pequeno.

**3 - E se o filtro usasse 15 varreduras?**

O atraso subiria para cerca de 7 a 8 varreduras, aproximadamente 0,12 a 0,13 s, e o robô andaria uns 18 a 21 px "cego" ao obstáculo novo. Objetos rápidos (como um carro a 190 px/s, que anda cerca de 25 px nesse tempo) ou que aparecem por pouco tempo poderiam simplesmente sumir da leitura filtrada, porque precisariam ocupar mais da metade da janela. Além disso, o filtro guardaria leituras antigas quando o robô gira, misturando direções diferentes. Em troca ficaria mais resistente a falhas seguidas, mas para um robô que protege uma pessoa no trânsito o atraso é pior que o ganho.

---

## 4. Segurança Temporal na Travessia

**1 - Cálculo do limite:**

limite = (RUA_ALTURA + 24 + GUIA) / velocidade × 1,35 + 0,4

limite = (170 + 24 + 42) / 156 × 1,35 + 0,4

limite = 236 / 156 × 1,35 + 0,4 = 1,5128 × 1,35 + 0,4 = 2,0423 + 0,4 ≈ **2,44 s**

Então o robô só começa a atravessar se ainda restarem mais de 2,44 s da fase PEDESTRE. No código, `LIMITE_TRAVESSIA` dá 2,4423 s.

**2 - Por que existem fases "todos vermelhos" de 1,5 s?**

São fases de limpeza do cruzamento. A TODOS_VERM_1 (entre AMARELO e PEDESTRE) dá tempo para os carros que passaram no amarelo, ou que entraram no último instante, saírem da faixa antes de o pedestre receber o verde. A TODOS_VERM_2 (entre PEDESTRE e VERDE) dá tempo para quem ainda está atravessando, como o robô e o tutor que andam mais devagar, terminar a travessia antes de os carros receberem o verde. Elas eliminam o risco de conflito na troca de fase, quando carros e pedestre ocupariam a faixa ao mesmo tempo por causa do tempo de reação ou de atraso de algum dos lados.

---

## 5. Avaliação Experimental

Comandos: `python dog_ia_v2.py --benchmark 20 --seed 1` e `python dog_ia_v2.py --benchmark 20 --seed 7`
(viagens em sequência Mercado → Farmácia → Padaria → Casa, repetidas; limite de 120 s por viagem)

**1 - Resultados:**

| Métrica | Seed 1 | Seed 7 |
|---|---|---|
| Taxa de sucesso | 100% (20/20) | 100% (20/20) |
| Tempo médio por viagem | 9,64 s | 9,64 s |
| Colisões | 0 | 0 |
| Quase-colisões (folga < 20 px) | 3 | 3 |
| Freios de emergência | 2 | 2 |
| Alertas vermelhos | 2 | 2 |
| Distância total | 15.458 px | 15.461 px |

**2 - Por que a seed fixa torna o experimento reproduzível e por que as duas seeds diferem?**

Toda a aleatoriedade do simulador (chegada dos carros, velocidade de cada um, quais são infratores, ruído gaussiano e dropout do LiDAR) vem do gerador pseudoaleatório do Python. Com a mesma seed ele gera exatamente a mesma sequência de números e o passo de tempo do benchmark é fixo (1/60 s), então rodar de novo com a mesma seed dá exatamente o mesmo resultado, o que permite comparar versões do código de forma justa.

Com outra seed a sequência muda: outros carros, outros infratores em outros momentos e outro ruído no sensor. Por isso as viagens individuais mudam (por exemplo, a viagem 5 levou 17,43 s com a seed 1 e 17,62 s com a seed 7, e a viagem 9 levou 18,32 s contra 15,62 s), assim como a distância percorrida e os momentos em que os freios acontecem. A média deu igual por coincidência: o semáforo tem ciclo fixo de 20 s e o tempo de cada travessia é dominado pela espera do sinal, então as diferenças entre viagens acabam se compensando. Isso mostra que 20 viagens e 2 seeds são poucas, e o ideal seria rodar mais seeds e comparar média e desvio.

**3 - Proposta de melhoria:**

Trocar a predição de velocidade/aceleração constante da zona varrida por uma que considere o semáforo: se o carro não é infrator conhecido e o sinal está vermelho para ele, projetar a parada na linha de retenção usando a desaceleração de conforto, em vez de projetar ele passando pela faixa. A métrica que eu esperaria melhorar é o número de freios de emergência (e o tempo médio da viagem, com menos paradas no meio da rua), porque a maioria dos freios observados foi causada por carros normais que ainda não tinham começado a frear. A métrica que poderia piorar é a de colisões/quase-colisões com infratores, porque o robô confiaria que o carro vai parar e reagiria mais tarde quando ele furar o sinal. Para compensar, a predição otimista só deveria valer enquanto o carro já está desacelerando a tempo.
