# -*- coding: utf-8 -*-
"""
Coletor de Macas para Roblox (Windows) - V6 Recuperacao automatica

F5: marca os 4 cantos INTERNOS da cerca + posicao do avatar
F6: salva uma imagem com as macas detectadas
F7: inicia a coleta e calibra o movimento
F8: para imediatamente
F9: pausa / retoma

Instalacao: py -m pip install -r requirements.txt
Execucao:   py coletor_macas_roblox.py
Teste:      py coletor_macas_roblox.py --teste imagem.png

AVISO: depende da camera acompanhar o personagem (com rastreamento
limitado do avatar como alternativa). Nao altera o Roblox nem garante
compatibilidade com jogos que bloqueiam teclas sinteticas.
"""

from __future__ import annotations

import argparse
import ctypes
import math
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
cv2.setNumThreads(2)


# Area precisa ser marcada pelo usuario diretamente na janela real do Roblox.
# Isto evita assumir posicoes fixas com zoom/camera diferentes.
# Margem minima entre o avatar e a cerca, em pixels de uma imagem 1128x807.
MARGEM_SEGURA_REFERENCIA = 43
MARGEM_FRUTA_REFERENCIA = 22

# Cores das frutas (HSV, escala do OpenCV)
CORES = {
    "rosa/vermelha": ((156, 95, 145), (179, 255, 255)),
    "verde": ((58, 110, 160), (100, 255, 255)),
    "amarela": ((17, 100, 155), (36, 255, 255)),
}


LOG_LOCK = threading.Lock()

def mensagem(s: str) -> None:
    linha = time.strftime("[%H:%M:%S] ") + s
    print(linha, flush=True)
    try:
        with LOG_LOCK:
            with (BASE_DIR / 'coletor_log.txt').open('a', encoding='utf-8') as f:
                f.write(linha + '\n')
    except OSError:
        pass


def margem_segura(w: int, h: int) -> float:
    return max(20.0, MARGEM_SEGURA_REFERENCIA * min(w / 1128.0, h / 807.0))


def distancia_cerca(poligono: np.ndarray, ponto) -> float:
    return float(cv2.pointPolygonTest(np.rint(poligono).astype(np.int32),
                                      (float(ponto[0]), float(ponto[1])), True))


def poligono_esta_ok(poligono: np.ndarray, jogador: np.ndarray, w: int, h: int) -> bool:
    pts = np.rint(poligono).astype(np.int32)
    if not cv2.isContourConvex(pts) or abs(cv2.contourArea(pts)) < (w*h*.04):
        return False
    if np.any(pts[:, 0] < 0) or np.any(pts[:, 0] >= w) or np.any(pts[:, 1] < 0) or np.any(pts[:, 1] >= h):
        return False
    return distancia_cerca(poligono, jogador) > margem_segura(w, h)


def desenhar_calibracao(frame: np.ndarray, pontos: list, fator: float):
    imagem = cv2.resize(frame, None, fx=fator, fy=fator)
    w, h = imagem.shape[1], imagem.shape[0]
    textos = ["1: canto SUPERIOR ESQUERDO", "2: canto SUPERIOR DIREITO",
              "3: canto INFERIOR DIREITO", "4: canto INFERIOR ESQUERDO",
              "5: SEU AVATAR (centro do boneco)"]
    n = len(pontos)
    if n < 5:
        msg = f"Clique {textos[n]} ({n+1}/5)"
    else:
        msg = "ENTER para salvar | R recomecar | ESC cancelar"
    # Caixa grande para facil leitura.
    cv2.rectangle(imagem, (0, 0), (w, 83), (23, 23, 23), -1)
    cv2.putText(imagem, msg, (12, 31), cv2.FONT_HERSHEY_SIMPLEX,
                .64, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(imagem, "Marque por DENTRO da cerca (nao em cima da madeira).",
                (12, 63), cv2.FONT_HERSHEY_SIMPLEX, .56, (120, 255, 240), 2, cv2.LINE_AA)
    coords = [(round(x*fator), round(y*fator)) for x,y in pontos]
    for i, pt in enumerate(coords):
        cor = (50, 230, 255) if i < 4 else (230, 60, 255)
        cv2.circle(imagem, pt, 7, cor, -1)
        cv2.putText(imagem, str(i+1), (pt[0]+11, pt[1]-11), cv2.FONT_HERSHEY_SIMPLEX, .7, (255,255,255), 2)
    if len(coords) >= 4:
        cv2.polylines(imagem, [np.asarray(coords[:4], np.int32)], True, (50,255,255), 3)
    elif len(coords) > 1:
        cv2.polylines(imagem, [np.asarray(coords[:4], np.int32)], False, (50,255,255), 2)
    if n == 5:
        dist = distancia_cerca(np.asarray(pontos[:4], np.float32), pontos[4]); limit = margem_segura(frame.shape[1],frame.shape[0]);
        status = f"Distancia da cerca: {dist:.0f}px (minimo {limit:.0f}px)"
        cv2.putText(imagem, status, (12, h-15), cv2.FONT_HERSHEY_SIMPLEX, .60,
                    ((80,255,80) if dist > limit else (60,60,255)), 2)
    return imagem


def selecionar_area(frame: np.ndarray):
    """Clique 4 cantos internos da cerca + seu avatar no mesmo frame."""
    h, w = frame.shape[:2]
    fator = min(1.0, 1150.0/w, 740.0/h)
    pontos = []
    titulo = "COLETOR - delimitar cerca e avatar"
    def ao_clicar(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN and len(pontos) < 5:
            pontos.append((float(x / fator), float(y / fator)))
    cv2.namedWindow(titulo, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(titulo, ao_clicar)
    try:
        while True:
            cv2.imshow(titulo, desenhar_calibracao(frame, pontos, fator))
            tecla = cv2.waitKey(35) & 0xff
            if tecla == 27: return None
            if tecla in (ord('r'), ord('R')): pontos.clear()
            if tecla in (13, 10) and len(pontos) == 5:
                poly = np.asarray(pontos[:4], np.float32)
                jogador = np.asarray(pontos[4], np.float32)
                if poligono_esta_ok(poly, jogador, w, h):
                    return poly, jogador
                mensagem("Selecao invalida: confira a ordem dos cantos e coloque o avatar longe da cerca. Aperte R e refaca.")
    finally:
        cv2.destroyWindow(titulo)

def reconhecer_macas(bgr: np.ndarray, poligono: np.ndarray):
    """Retorna lista [{x, y, cor}] com base em cores e formatos pequenos/redondos."""
    altura, largura = bgr.shape[:2]
    escala = min(largura / 1919.0, altura / 1020.0)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    permitido = np.zeros((altura, largura), dtype=np.uint8)
    cv2.fillPoly(permitido, [np.rint(poligono).astype(np.int32)], 255)
    # Placas da loja ficam junto ao topo da cerca; nao sao frutas.
    # Rejeitar so a faixa superior estreita, mantendo as frutas abaixo.
    topo = int(np.min(poligono[:2, 1]) + max(15, round(altura * .034)))
    permitido[:min(altura, max(0, topo)), :] = 0
    # Margem para evitar objetos fora da cerca / UI.
    margem = max(3, int(7 * escala))
    kernel_margem = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margem + 1, 2 * margem + 1))
    permitido = cv2.erode(permitido, kernel_margem)
    reconhecidas = []

    for nome, (minimo, maximo) in CORES.items():
        mascara = cv2.inRange(hsv, np.array(minimo, np.uint8), np.array(maximo, np.uint8))
        mascara = cv2.bitwise_and(mascara, permitido)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contorno in contornos:
            area = cv2.contourArea(contorno)
            if not (27 * escala**2 <= area <= 950 * escala**2):
                continue
            x, y, w, h = cv2.boundingRect(contorno)
            if not (6 * escala <= w <= 60 * escala and 6 * escala <= h <= 60 * escala):
                continue
            if not (0.52 <= w / float(h) <= 1.75):
                continue
            momento = cv2.moments(contorno)
            if momento['m00'] <= 0:
                continue
            cx, cy = momento['m10'] / momento['m00'], momento['m01'] / momento['m00']
            reconhecidas.append({'x': float(cx), 'y': float(cy), 'cor': nome})

    # Eliminar duplicatas: centros de uma mesma maca podem aparecer em duas faixas HSV.
    sem_duplicatas = []
    for fruta in sorted(reconhecidas, key=lambda f: {"rosa/vermelha": 0, "amarela": 1, "verde": 2}[f['cor']]):
        if not any(math.hypot(fruta['x']-outra['x'], fruta['y']-outra['y']) < max(7, 12*escala)
                   for outra in sem_duplicatas):
            sem_duplicatas.append(fruta)
    return sem_duplicatas


def imagem_marcada(bgr: np.ndarray, poligono: np.ndarray, jogador, macas, destino=None):
    saida = bgr.copy()
    cv2.polylines(saida, [np.rint(poligono).astype(np.int32)], True, (235, 235, 255), 2)
    # Linha VERDE: regiao onde o centro do avatar pode navegar com margem.
    hh, ww = bgr.shape[:2]
    mapa = np.zeros((hh, ww), np.uint8)
    cv2.fillPoly(mapa, [np.rint(poligono).astype(np.int32)], 255)
    erosao = max(3, round(margem_segura(ww, hh)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*erosao+1, 2*erosao+1))
    mapa = cv2.erode(mapa, kernel)
    contornos, _ = cv2.findContours(mapa, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(saida, contornos, -1, (65, 255, 65), 2)
    for maca in macas:
        cor = (255, 50, 255) if maca['cor'] == 'rosa/vermelha' else ((100, 255, 20) if maca['cor'] == 'verde' else (0, 230, 255))
        centro = (round(maca['x']), round(maca['y']))
        cv2.circle(saida, centro, 17, cor, 2)
    cx, cy = round(jogador[0]), round(jogador[1])
    cv2.drawMarker(saida, (cx, cy), (255, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=30, thickness=3)
    if destino is not None:
        alvo = (round(destino['x']), round(destino['y']))
        cv2.line(saida, (cx, cy), alvo, (255, 255, 255), 3)
        cv2.circle(saida, alvo, 25, (255, 255, 255), 3)
    cv2.rectangle(saida, (8, 8), (min(760,ww-4), 61), (35, 35, 35), -1)
    cv2.putText(saida, f"{len(macas)} macas | branco=cerca | verde=limite seguro | +=avatar", (17, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)
    return saida




def estimar_por_macas(antes: np.ndarray, depois: np.ndarray, poligono: np.ndarray):
    """Estima quanto o CENARIO se moveu observando macas fixas no chao.

    Diferente de rastrear cada tábua, não exige que os pixels sejam iguais:
    maçãs podem girar/animar e algumas podem desaparecer durante a coleta.
    Testa deslocamentos candidatos, confirma que vários centros concordam,
    e rejeita combinações casuais. A cerca acompanha esse deslocamento.
    """
    if antes.shape != depois.shape:
        return None, 0., 'capturas de tamanhos diferentes'
    h, w = antes.shape[:2]
    # A cerca se move no quadro; ampliar um pouco a busca nos limites.
    c = poligono.mean(axis=0)
    maior = c + (poligono-c)*1.07
    velhas = reconhecer_macas(antes, maior)
    novas = reconhecer_macas(depois, maior)
    if len(velhas) < 6 or len(novas) < 6:
        return None, 0., f'poucas macas para rastrear ({len(velhas)}->{len(novas)})'
    deslocamentos = []
    for cor in CORES:
        p = np.asarray([[f['x'], f['y']] for f in velhas if f['cor']==cor], dtype=np.float32).reshape(-1,2)
        q = np.asarray([[f['x'], f['y']] for f in novas if f['cor']==cor], dtype=np.float32).reshape(-1,2)
        if len(p) and len(q):
            candidatos = (q[:, None, :] - p[None, :, :]).reshape(-1,2)
            candidatos = candidatos[np.linalg.norm(candidatos, axis=1) < max(260., min(h,w)*.29)]
            if len(candidatos):
                deslocamentos.append(candidatos)
    if not deslocamentos:
        return None, 0., 'nenhum par de macas'
    delta = np.concatenate(deslocamentos)
    # Usa grade de votos e melhora o centro usando mediana robusta.
    grade = np.rint(delta / 4).astype(np.int32)
    celulas, indices, contagens = np.unique(grade, axis=0, return_inverse=True, return_counts=True)
    candidatos = np.argsort(contagens)[-min(15, len(contagens)):][::-1]
    melhor_votos, melhor_delta = -1, None
    for i in candidatos:
        inicial = celulas[i]*4.0
        proximos = delta[np.linalg.norm(delta-inicial, axis=1) <= 7.0]
        if len(proximos) < 5:
            continue
        medio = np.median(proximos, axis=0)
        # Quantidade de frutas antigas que encontra uma correspondente UNICA
        # da mesma cor, perto da posicao prevista.
        confirmados = 0
        for cor in CORES:
            p = np.asarray([[f['x'],f['y']] for f in velhas if f['cor']==cor],np.float32).reshape(-1,2)
            q = np.asarray([[f['x'],f['y']] for f in novas if f['cor']==cor],np.float32).reshape(-1,2)
            if not len(p) or not len(q):
                continue
            dist = np.linalg.norm(p[:,None,:] + medio - q[None,:,:],axis=2)
            while dist.size:
                ii,jj = np.unravel_index(np.argmin(dist),dist.shape)
                if dist[ii,jj] > 5.5:
                    break
                confirmados += 1
                dist[ii,:] = 1e6
                dist[:,jj] = 1e6
        if confirmados > melhor_votos:
            melhor_delta, melhor_votos = medio, confirmados
    disponiveis = min(len(velhas),len(novas))
    if melhor_delta is None or melhor_votos < max(6,int(disponiveis*.28)):
        return None, 0., f'macas sem deslocamento comum (melhor apoio {melhor_votos}/{disponiveis})'
    qualidade = min(1., melhor_votos/max(8.,disponiveis*.68))
    mat = np.asarray([[1., 0., melhor_delta[0]], [0., 1., melhor_delta[1]]],np.float32)
    # Refinar rotacao/escala leves do cenario usando pares confirmados.
    origem, destino = [], []
    for cor in CORES:
        pp = np.asarray([[f['x'],f['y']] for f in velhas if f['cor']==cor],np.float32).reshape(-1,2)
        qq = np.asarray([[f['x'],f['y']] for f in novas if f['cor']==cor],np.float32).reshape(-1,2)
        if not len(pp) or not len(qq):
            continue
        dist = np.linalg.norm(pp[:,None,:]+melhor_delta-qq[None,:,:],axis=2)
        while dist.size:
            ii,jj = np.unravel_index(np.argmin(dist),dist.shape)
            if dist[ii,jj] > 5.5:
                break
            origem.append(pp[ii]); destino.append(qq[jj]); dist[ii,:]=1e6; dist[:,jj]=1e6
    if len(origem) >= 9:
        refino, mascara = cv2.estimateAffinePartial2D(np.asarray(origem),np.asarray(destino),
            method=cv2.RANSAC, ransacReprojThreshold=3.5, maxIters=800, confidence=.995)
        inliers = int(np.sum(mascara)) if mascara is not None else 0
        validado = _avaliar_transformacao(refino, antes, depois, poligono.mean(axis=0),
                                           inliers, len(origem), 'macas RANSAC')
        if validado is not None and inliers >= max(7, .55 * len(origem)):
            return validado[0], min(qualidade, validado[1]), f'macas + rotacao ({inliers}/{disponiveis})'
    return mat, float(qualidade), f'macas rastreadas ({melhor_votos}/{disponiveis})'


def estimar_movimento_cenario(antes: np.ndarray, depois: np.ndarray, poligono: np.ndarray):
    """Rastreia postes/solo proximos a cerca com fluxo optico; retorna delta e qualidade.

    Sem confianca, o bot nao continua andando, para nao sair do cercado.
    """
    altura, largura = antes.shape[:2]
    cinza_antes = cv2.cvtColor(antes, cv2.COLOR_BGR2GRAY)
    cinza_depois = cv2.cvtColor(depois, cv2.COLOR_BGR2GRAY)
    mascara = np.zeros((altura, largura), np.uint8)
    espessura = max(30, round(min(largura / 1128, altura / 807)*75))
    cv2.polylines(mascara, [np.rint(poligono).astype(np.int32)], True, 255, espessura)
    # Ignorar botoes de menu e rodape da interface.
    mascara[:round(altura*.13)] = 0
    mascara[round(altura*.92):] = 0
    pts = cv2.goodFeaturesToTrack(cinza_antes, maxCorners=170, qualityLevel=.022,
                                  minDistance=8, mask=mascara, blockSize=7)
    if pts is None or len(pts) < 9:
        return np.zeros(2, np.float32), 0.0
    nov_pts, status, erro = cv2.calcOpticalFlowPyrLK(
        cinza_antes, cinza_depois, pts, None,
        winSize=(27,27), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, .01))
    if nov_pts is None:
        return np.zeros(2, np.float32), 0.0
    validos = (status.ravel() == 1) & (erro.ravel() < 42)
    if np.count_nonzero(validos) < 9:
        return np.zeros(2, np.float32), 0.0
    delta = (nov_pts[validos] - pts[validos]).reshape(-1, 2)
    media = np.median(delta, axis=0)
    dist = np.linalg.norm(delta - media, axis=1)
    coerentes = dist < max(3.0, min(largura/1128.0, altura/807.0)*6.0)
    apoio = int(np.count_nonzero(coerentes))
    fracao = float(apoio / len(delta))
    qualidade = min(1.0, apoio/20.0) * fracao
    if apoio < 9 or fracao < .48 or np.linalg.norm(media) > 95:
        return np.zeros(2, np.float32), 0.0
    return np.median(delta[coerentes], axis=0).astype(np.float32), qualidade

def _avaliar_transformacao(m, antes, depois, jogador, inliers, pontos, metodo):
    """Valida uma transformacao afim (rotacao leve + translacao)."""
    if m is None or not np.all(np.isfinite(m)):
        return None
    h, w = antes.shape[:2]
    a, b, tx = [float(v) for v in m[0]]
    c, d, ty = [float(v) for v in m[1]]
    s1 = math.hypot(a, c)
    s2 = math.hypot(b, d)
    det = a*d-b*c
    angulo = math.degrees(math.atan2(c,a))
    # Movimentos maiores que estes provavelmente sao troca de camera/zoom.
    if not (.93 <= s1 <= 1.07 and .93 <= s2 <= 1.07 and det > 0 and abs(angulo) <= 8):
        return None
    centro = np.asarray(jogador, np.float32)
    movimento = m[:, :2] @ centro + m[:, 2] - centro
    if float(np.linalg.norm(movimento)) > max(95., min(w,h)*.13):
        return None
    if pontos < 7 or inliers < 7:
        return None
    qualidade = min(1.0, inliers/20.0) * min(1., inliers/float(pontos))
    return np.asarray(m, np.float32), float(qualidade), metodo


def estimar_transformacao_cenario(antes: np.ndarray, depois: np.ndarray,
                                 poligono: np.ndarray, jogador: np.ndarray):
    """Rastreia a cerca e solo com RANSAC, aceita camera parada e rotacao leve.

    Ao falhar, retorna motivo para orientar o diagnostico. Nao inventa movimento.
    """
    h, w = antes.shape[:2]
    if antes.shape != depois.shape:
        return None, 0., 'tamanho das capturas mudou'
    frutas_mat, frutas_conf, frutas_motivo = estimar_por_macas(antes, depois, poligono)
    if frutas_mat is not None and frutas_conf >= .35:
        return frutas_mat, frutas_conf, frutas_motivo
    cinza1 = cv2.cvtColor(antes, cv2.COLOR_BGR2GRAY)
    cinza2 = cv2.cvtColor(depois, cv2.COLOR_BGR2GRAY)
    escala = min(w/1128., h/807.)
    mascara = np.zeros((h,w), np.uint8)
    # Usa a cerca e o chao em conjunto. A versao 3 olhava so uma faixa estreita.
    raio_cerca = max(45, int(100*escala))
    cv2.fillPoly(mascara, [np.rint(poligono).astype(np.int32)], 255)
    cv2.polylines(mascara, [np.rint(poligono).astype(np.int32)], True, 255, raio_cerca)
    # Botões do Roblox no topo e na parte de baixo nao devem entrar no rastreamento.
    mascara[:int(h*.19), :] = 0
    mascara[int(h*.88):, :] = 0
    cv2.circle(mascara, tuple(np.rint(jogador).astype(int)), max(37,int(56*escala)), 0, -1)
    # Exclui regioes tipicas das barras laterais; depende do tamanho da janela.
    mascara[:, :int(w*.12)] = 0
    mascara[:, int(w*.92):] = 0
    pontos = cv2.goodFeaturesToTrack(cinza1, maxCorners=420, qualityLevel=.009,
                   minDistance=max(5,int(7*escala)), mask=mascara, blockSize=5)
    info = []
    if pontos is not None and len(pontos) >= 8:
        destino, status, erros = cv2.calcOpticalFlowPyrLK(
            cinza1, cinza2, pontos, None, winSize=(41,41), maxLevel=4,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35,.01))
        if destino is not None and status is not None:
            retorno, back_status, _ = cv2.calcOpticalFlowPyrLK(
                cinza2, cinza1, destino, None, winSize=(41,41), maxLevel=4,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,35,.01))
            if retorno is None or back_status is None:
                retorno = pontos.copy()
                back_status = np.zeros_like(status)
            validos = (status.ravel()==1) & (back_status.ravel()==1)
            validos &= np.linalg.norm((retorno-pontos).reshape(-1,2), axis=1) < max(3.,4.*escala)
            src = pontos.reshape(-1,2)[validos]
            dst = destino.reshape(-1,2)[validos]
            info.append(f'LK {len(src)}/{len(pontos)}')
            if len(src) >= 8:
                # RANSAC rejeita outras animacoes, como frutas que surgem/desaparecem.
                m, masc_inliers = cv2.estimateAffinePartial2D(src,dst,
                    method=cv2.RANSAC, ransacReprojThreshold=max(3.,4.5*escala),
                    maxIters=3000, confidence=.995, refineIters=12)
                ni = int(masc_inliers.sum()) if masc_inliers is not None else 0
                resultado = _avaliar_transformacao(m, antes,depois,jogador,ni,len(src),'fluxo optico RANSAC')
                if resultado is not None and resultado[1] >= .22:
                    return resultado
                info.append(f'RANSAC {ni}/{len(src)}')
    else:
        info.append(f'LK pontos {0 if pontos is None else len(pontos)}')
    # Plano B: reconhecimento de detalhes do chao e da madeira com ORB.
    orb = cv2.ORB_create(nfeatures=1100, fastThreshold=8)
    k1, d1 = orb.detectAndCompute(cinza1,mascara)
    k2, d2 = orb.detectAndCompute(cinza2,mascara)
    if d1 is not None and d2 is not None and len(k1)>=15 and len(k2)>=15:
        pares = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1,d2,k=2)
        selecionados = [par[0] for par in pares if len(par)==2 and par[0].distance < .73*par[1].distance]
        info.append(f'ORB pares {len(selecionados)}')
        if len(selecionados) >= 9:
            src = np.float32([k1[par.queryIdx].pt for par in selecionados])
            dst = np.float32([k2[par.trainIdx].pt for par in selecionados])
            m,msk = cv2.estimateAffinePartial2D(src,dst, method=cv2.RANSAC,
                ransacReprojThreshold=max(3., 4.5*escala),maxIters=3000,confidence=.995,refineIters=10)
            ni=int(msk.sum()) if msk is not None else 0
            resultado=_avaliar_transformacao(m,antes,depois,jogador,ni,len(src),'ORB RANSAC')
            if resultado is not None and resultado[1] >= .22:
                return resultado
            info.append(f'ORB RANSAC {ni}/{len(src)}')
    # Plano C: correlacao de fase somente na area do chao/cerca. Aceita translação.
    # Ajuda caso a camera esteja totalmente fixa e frutas/boneco animem.
    x1=max(0, int(np.min(poligono[:,0])-25*escala))
    x2=min(w, int(np.max(poligono[:,0])+25*escala))
    y1=max(int(h*.20), int(np.min(poligono[:,1])-25*escala))
    y2=min(int(h*.87), int(np.max(poligono[:,1])+25*escala))
    if x2-x1 > 100 and y2-y1 > 100:
        r1=cinza1[y1:y2,x1:x2].astype(np.float32)
        r2=cinza2[y1:y2,x1:x2].astype(np.float32)
        # Gradiente reduz influencia de mudancas globais de iluminacao.
        r1=cv2.Laplacian(cv2.GaussianBlur(r1,(3,3),0),cv2.CV_32F)
        r2=cv2.Laplacian(cv2.GaussianBlur(r2,(3,3),0),cv2.CV_32F)
        hann=cv2.createHanningWindow((r1.shape[1],r1.shape[0]),cv2.CV_32F)
        desloc, resposta=cv2.phaseCorrelate(r1,r2,hann)
        info.append(f'fase resposta {resposta:.2f} desloc {desloc[0]:.0f},{desloc[1]:.0f}')
        if resposta >= .33 and math.hypot(*desloc) <= max(95.,min(w,h)*.13):
            m=np.asarray([[1.,0.,desloc[0]],[0.,1.,desloc[1]]],np.float32)
            return m,float(min(.85,resposta)),'correlacao de fase'
    camera_fixa, q_fixa, porque_fixa = estimar_camera_parada(antes, depois, poligono, jogador)
    if camera_fixa is not None:
        return camera_fixa, q_fixa, porque_fixa
    info.append(porque_fixa)
    return None,0.0,'; '.join(info)




def estimar_camera_parada(antes: np.ndarray, depois: np.ndarray,
                          poligono: np.ndarray, jogador: np.ndarray):
    """Reconhece camera fixa por varios retalhos ESTATICOS do chao.

    Importante ao chegar perto da extremidade: a camera deixa de seguir o
    jogador, mas o avatar continua andando na imagem. Nessa situacao, o
    rastreamento da cerca deve retornar uma identidade, nao um erro.
    """
    if antes.shape != depois.shape:
        return None, 0., 'tamanho de janela diferente'
    h, w = antes.shape[:2]
    a = cv2.cvtColor(antes, cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(depois, cv2.COLOR_BGR2GRAY)
    centro = np.mean(poligono, axis=0)
    escala = min(w/1128., h/807.)
    raio = max(20, int(29 * escala))
    amostras = []
    # Revestimento e cerca (nao o personagem) servem de referencia visual.
    for frac in (.15,.38,.60):
        for canto in poligono:
            amostras.append(centro*(1-frac) + canto*frac)
    amostras += [centro + (p-centro)*.30 for p in
                 (0.5*(poligono[0]+poligono[1]),
                  0.5*(poligono[1]+poligono[2]),
                  0.5*(poligono[2]+poligono[3]),
                  0.5*(poligono[3]+poligono[0]))]
    positivos, tentados = 0, 0
    for pos in amostras:
        x, y = np.rint(pos).astype(int)
        if x-raio < 8 or x+raio >= w-8 or y-raio < h*.15 or y+raio >= h*.88:
            continue
        if np.linalg.norm(pos-jogador) < max(75, 82*escala):
            continue
        p = a[y-raio:y+raio, x-raio:x+raio]
        q = b[y-raio:y+raio, x-raio:x+raio]
        if np.std(p) < 9.:  # sem detalhes visuais, fraca referencia
            continue
        tentados += 1
        # Correlação normalizada cancela mudancas leves de iluminacao.
        correlacao = float(cv2.matchTemplate(p, q, cv2.TM_CCOEFF_NORMED)[0,0])
        if correlacao >= .87:
            positivos += 1
    proporcao = positivos/max(1,tentados)
    if positivos >= 4 and proporcao >= .56:
        identidade = np.array([[1.,0.,0.],[0.,1.,0.]], dtype=np.float32)
        return identidade, float(min(1.0, .45+.45*proporcao)), f'camera fixa ({positivos}/{tentados} pontos)'
    return None, 0., f'camera nao comprovada ({positivos}/{tentados} pontos)'



def registrar_falha_rastreamento(antes: np.ndarray, depois: np.ndarray,
                                 poligono: np.ndarray, jogador: np.ndarray):
    """Salva capturas antes/depois do primeiro passo que deu problema."""
    try:
        for nome,img in [('diagnostico_antes.png',antes),('diagnostico_depois.png',depois)]:
            marcado=img.copy()
            cv2.polylines(marcado,[np.rint(poligono).astype(np.int32)],True,(255,255,255),3)
            cv2.drawMarker(marcado,tuple(np.rint(jogador).astype(int)),(0,255,255),
                          markerType=cv2.MARKER_CROSS,markerSize=34,thickness=3)
            cv2.imwrite(str(BASE_DIR/nome),marcado)
        mensagem('Diagnosticos salvos: diagnostico_antes.png e diagnostico_depois.png')
    except Exception as e:
        mensagem(f'Falha ao salvar capturas de diagnostico: {e}')


def localizar_avatar(antes: np.ndarray, depois: np.ndarray, jogador):
    """Rastreia um pequeno recorte do avatar; ignora matches pouco confiaveis."""
    altura, largura = antes.shape[:2]
    escala = min(largura / 1919.0, altura / 1020.0)
    raio = max(11, round(15 * escala))
    busca = max(28, round(85 * escala))
    x, y = [round(v) for v in jogador]
    if x - raio < 0 or x + raio >= largura or y - raio < 0 or y + raio >= altura:
        return np.asarray(jogador, np.float32), 0.0
    g1 = cv2.cvtColor(antes, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(depois, cv2.COLOR_BGR2GRAY)
    modelo = g1[y - raio:y + raio + 1, x - raio:x + raio + 1]
    xa, ya = max(0, x-busca-raio), max(0, y-busca-raio)
    xb, yb = min(largura, x+busca+raio+1), min(altura, y+busca+raio+1)
    area = g2[ya:yb, xa:xb]
    if area.shape[0] < modelo.shape[0] or area.shape[1] < modelo.shape[1]:
        return np.asarray(jogador, np.float32), 0.0
    m = cv2.matchTemplate(area, modelo, cv2.TM_CCOEFF_NORMED)
    _, confianca, _, pos = cv2.minMaxLoc(m)
    resultado = np.array([xa + pos[0] + raio, ya + pos[1] + raio], np.float32)
    if confianca < .60 or np.linalg.norm(resultado - jogador) > busca:
        return np.asarray(jogador, np.float32), float(confianca)
    return resultado, float(confianca)


def teste_offline(caminho: str):
    imagem = cv2.imread(caminho)
    if imagem is None:
        raise RuntimeError(f"Nao consegui abrir a imagem: {caminho}")
    h, w = imagem.shape[:2]
    # Modo offline: exemplo do print enviado, sem aplicacao ao jogo ao vivo.
    poligono = np.asarray([[.248*w,.218*h],[.712*w,.218*h],[.766*w,.885*h],[.174*w,.885*h]],np.float32)
    jogador = np.array([.450*w,.633*h], np.float32)
    macas = reconhecer_macas(imagem, poligono)
    saida = BASE_DIR / 'deteccao_macas.png'
    cv2.imwrite(str(saida), imagem_marcada(imagem, poligono, jogador, macas))
    print(f"Identificadas {len(macas)} macas/frutas. Imagem com circulos: {saida}")
    for cor in CORES:
        print(f"   {cor}: {sum(m['cor'] == cor for m in macas)}")


class Bot:
    def __init__(self):
        # Importados somente no Windows / modo ao vivo.
        global keyboard, mss, pydirectinput, win32gui
        import keyboard
        import mss
        import pydirectinput
        import win32gui
        pydirectinput.PAUSE = 0

        self.parar_evento = threading.Event()
        self.pausar_evento = threading.Event()
        self.thread = None
        self.hwnd = None
        self.poligono = None
        self.jogador = None
        self.matriz = None
        self.frame_size = None
        self.bloqueadas = []
        self.ultimo_alvo = None
        self.passos_alvo = 0
        self.area_marcada = None  # (poligono, avatar, frame_size); valido neste processo
        self.calibrando_area = False
        self.avisos_localizacao = 0
        self.medicoes = 0
        self.patrulha_indice = 0
        self.patrulha_alvo = None
        self.erros_sem_movimento = 0
        self.alvo_atual = None
        self.ultimo_proximo = None
        self.contagem_proximo = 0
        # V6: default RAPIDO, alteravel por 1/2/3 no terminal.
        self.nivel_velocidade = 2
        self.passo_modelado = 0
        self.falhas_rastreamento = 0
        self.ultima_falha_salva = 0.0
        self.ultimo_aguardo = 0.0
        self.ultima_captura_valida = None
        self.falha_passo = None

    def mudar_velocidade(self, nivel: int):
        if nivel not in (1,2,3):
            return
        self.nivel_velocidade = nivel
        nome = {1:'NORMAL', 2:'RAPIDO', 3:'TURBO'}[nivel]
        mensagem(f'Velocidade alterada: {nome}. Seguranca da cerca continua ativa.')

    def recuperar_sem_mover(self, sct):
        """Nao pausa o bot permanentemente; tenta atualizar o marco da arena.

        Nao manda teclas quando a confianca nao basta para manter a cerca.
        A rotina principal continua e volta a andar quando se recupera.
        """
        if self.ultima_captura_valida is None:
            time.sleep(.12)
            return False
        atual = self.capturar(sct)
        m, q, metodo = estimar_transformacao_cenario(
            self.ultima_captura_valida, atual, self.poligono, self.jogador)
        if m is None:
            time.sleep(.20)
            return False
        new_poly = cv2.transform(self.poligono.reshape(1,-1,2),m).reshape(-1,2)
        cena_avatar = cv2.transform(self.jogador.reshape(1,1,2),m).reshape(2)
        new_jogador = self.jogador.copy()
        if self.matriz is not None and self.falha_passo is not None:
            tecla, tempo = self.falha_passo
            eixo = 0 if tecla in ('w','s') else 1
            sinal = 1 if tecla in ('w','d') else -1
            new_jogador = cena_avatar-self.matriz[:,eixo]*sinal*tempo
        # Evita aceitar correcao que coloque o jogador na madeira.
        if distancia_cerca(new_poly, new_jogador) <= margem_segura(*self.frame_size)*1.1:
            return False
        self.poligono = new_poly.astype(np.float32)
        self.jogador = new_jogador.astype(np.float32)
        self.ultima_captura_valida = atual
        self.falhas_rastreamento = 0
        self.falha_passo = None
        mensagem(f'Referencia da arena recuperada: {metodo}, confianca {q:.2f}.')
        return True

    def encontrar_janela(self):
        candidatos = []
        def enumerar(hwnd, _):
            titulo = win32gui.GetWindowText(hwnd).strip()
            if not win32gui.IsWindowVisible(hwnd) or titulo.lower() != 'roblox':
                return
            if win32gui.IsIconic(hwnd):
                return
            l, t, r, b = win32gui.GetClientRect(hwnd)
            if (r-l) > 500 and (b-t) > 300:
                candidatos.append(((r-l)*(b-t), hwnd))
        win32gui.EnumWindows(enumerar, None)
        if not candidatos:
            raise RuntimeError("Janela Roblox nao encontrada. Abra o jogo antes de iniciar.")
        return max(candidatos)[1]

    def jogo_em_foco(self):
        if self.hwnd is None or not win32gui.IsWindow(self.hwnd):
            return False
        return win32gui.GetForegroundWindow() == self.hwnd

    def capturar(self, sct):
        if not win32gui.IsWindow(self.hwnd):
            raise RuntimeError('A janela do Roblox foi fechada.')
        x, y = win32gui.ClientToScreen(self.hwnd, (0, 0))
        l, t, r, b = win32gui.GetClientRect(self.hwnd)
        largura, altura = r-l, b-t
        if largura < 400 or altura < 250:
            raise RuntimeError('A janela do Roblox esta pequena demais.')
        if self.frame_size is not None and (largura, altura) != self.frame_size:
            raise RuntimeError('Tamanho do Roblox mudou. Pare com F8 e inicie novamente.')
        frame = np.asarray(sct.grab({'left': x, 'top': y, 'width': largura, 'height': altura}))
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def marcar_cerca(self):
        if self.thread is not None and self.thread.is_alive():
            mensagem('Pare primeiro com F8 antes de redefinir a cerca.')
            return
        if self.calibrando_area:
            return
        self.calibrando_area = True
        try:
            self.hwnd = self.encontrar_janela()
            # Se iniciou digitando '5' no terminal, a janela preta esta na frente.
            # Aguardar o usuario clicar no jogo antes da captura; evita gravar o CMD.
            if not self.jogo_em_foco():
                mensagem('Clique no Roblox em ate 20 segundos para fotografar a cerca...')
                fim = time.monotonic() + 20.0
                while not self.jogo_em_foco() and time.monotonic() < fim:
                    time.sleep(.12)
                if not self.jogo_em_foco():
                    mensagem('Nao foi possivel fotografar o jogo. Digite 5 novamente.')
                    return
            time.sleep(.25)
            with mss.MSS() as sct:
                self.frame_size = None
                frame = self.capturar(sct)
            mensagem('F5: marque os quatro cantos INTERNOS (superior esquerdo, superior direito, inferior direito, inferior esquerdo) e depois seu avatar. ENTER confirma.')
            pontos = selecionar_area(frame)
            if pontos is None:
                mensagem('Calibracao cancelada. Nada foi alterado.')
                return
            poly, jogador = pontos
            self.area_marcada = (poly.copy(), jogador.copy(), (frame.shape[1], frame.shape[0]))
            self.poligono = poly.copy()
            self.jogador = jogador.copy()
            mensagem(f'CERCA SALVA: avatar a {distancia_cerca(poly,jogador):.0f}px da borda. Agora clique no Roblox e aperte F7 (ou 7+Enter).')
            imagem = imagem_marcada(frame, poly, jogador,
                                    reconhecer_macas(frame, poly))
            cv2.imwrite(str(BASE_DIR / 'cerca_calibrada.png'), imagem)
            mensagem('Previa salva: cerca_calibrada.png')
        except Exception as e:
            mensagem(f'Nao consegui marcar cerca: {e}')
            traceback.print_exc()
        finally:
            self.calibrando_area = False

    def liberar_teclas(self):
        for tecla in ('w', 'a', 's', 'd'):
            try: pydirectinput.keyUp(tecla)
            except Exception: pass

    def mover(self, tecla: str, segundos: float):
        if self.parar_evento.is_set() or self.pausar_evento.is_set() or not self.jogo_em_foco():
            return False
        pydirectinput.keyDown(tecla)
        try:
            fim = time.monotonic() + segundos
            while time.monotonic() < fim:
                if self.parar_evento.is_set() or self.pausar_evento.is_set() or not self.jogo_em_foco():
                    return False
                time.sleep(min(.02, max(.001, fim-time.monotonic())))
            return True
        finally:
            pydirectinput.keyUp(tecla)

    def medir_passo(self, sct, tecla: str, duracao: float, atualizar: bool = True):
        if not self.jogo_em_foco():
            return None, None
        anterior = self.capturar(sct)
        self.ultima_captura_valida = anterior
        p_antes = self.jogador.copy()
        if not self.mover(tecla, duracao):
            return None, None
        time.sleep(.045)
        posterior = self.capturar(sct)
        transformacao, confianca_cenario, metodo = estimar_transformacao_cenario(
            anterior, posterior, self.poligono, p_antes)
        if transformacao is None:
            # Nao termina a coleta na primeira falha: tenta de novo com a camera estabilizada.
            for tentativa in range(2):
                if self.parar_evento.is_set() or self.pausar_evento.is_set():
                    return None, (0.,0.)
                time.sleep(.19)
                posterior = self.capturar(sct)
                transformacao, confianca_cenario, metodo = estimar_transformacao_cenario(
                    anterior, posterior, self.poligono, p_antes)
                if transformacao is not None:
                    mensagem(f'Rastreamento recuperado automaticamente: {metodo}')
                    break
            if transformacao is None:
                self.falhas_rastreamento += 1
                if self.falhas_rastreamento == 1 or self.falhas_rastreamento % 8 == 0:
                    mensagem(f'Imagem incerta apos {tecla.upper()}: {metodo}. '
                             'Recuperando automaticamente, sem encerrar a coleta.')
                if self.falhas_rastreamento == 1 and time.monotonic()-self.ultima_falha_salva > 15:
                    registrar_falha_rastreamento(anterior, posterior, self.poligono, self.jogador)
                    self.ultima_falha_salva = time.monotonic()
                # Recuperacao do rastreamento nao cria estado permanente de pausa.
                self.ultima_captura_valida = anterior
                self.falha_passo = (tecla, duracao)
                return None, (0.0, 0.0)
        self.falhas_rastreamento = 0
        poligono_novo = cv2.transform(self.poligono.reshape(1,-1,2),transformacao).reshape(-1,2)
        cena_na_posicao_avatar = cv2.transform(p_antes.reshape(1,1,2),transformacao).reshape(2)
        p_novo, confianca_avatar = localizar_avatar(anterior, posterior, p_antes)
        movimento_cenario = float(np.linalg.norm(cena_na_posicao_avatar-p_antes))
        # V6: perto do limite da camera, o personagem se desloca na tela
        # enquanto o CENARIO fica parado. Isso e normal, nao e uma falha.
        prevista = p_antes.copy()
        if self.matriz is not None:
            eixo = 0 if tecla in ('w','s') else 1
            sinal = 1 if tecla in ('w','d') else -1
            relativo_esperado = self.matriz[:,eixo] * sinal * duracao
            prevista = cena_na_posicao_avatar - relativo_esperado
        if movimento_cenario >= 3.5:
            # Camera segue o avatar: o centro do boneco fica quase no lugar.
            if confianca_avatar < .88 or np.linalg.norm(p_novo-p_antes) > 15:
                p_novo=p_antes.copy()
        else:
            # Camera parada: tenta verificar o avatar na posicao prevista;
            # usa odometria de curto alcance se o sprite animado nao casar.
            erro_modelo = float(np.linalg.norm(p_novo-prevista))
            if self.matriz is not None and (confianca_avatar < .88 or erro_modelo > 18):
                candidato = prevista.astype(np.float32)
                borda_prevista = distancia_cerca(poligono_novo,candidato)
                if borda_prevista > margem_segura(*self.frame_size)*1.15:
                    p_novo = candidato
                    self.passo_modelado += 1
                    if self.passo_modelado % 12 == 1:
                        mensagem(f'Camera parada: posicao estimada do avatar; '
                                 f'confianca visual {confianca_avatar:.2f}.')
                else:
                    # Perto da madeira, nao perder o limite para manter um passo.
                    mensagem('Avatar junto a borda, recalculando rota para o centro.')
                    p_novo = candidato
            elif confianca_avatar < .65:
                p_novo=p_antes.copy()
            else:
                self.passo_modelado = 0
        # Diferenca entre deslocamento do cenario e deslocamento do avatar.
        relativo = cena_na_posicao_avatar-p_novo
        if atualizar:
            if self.bloqueadas:
                anterior_bloqueadas=np.asarray(self.bloqueadas,np.float32).reshape(1,-1,2)
                self.bloqueadas=[x for x in cv2.transform(anterior_bloqueadas,transformacao).reshape(-1,2)]
            if self.ultimo_alvo is not None:
                self.ultimo_alvo=cv2.transform(np.asarray(self.ultimo_alvo,np.float32).reshape(1,1,2),
                                                transformacao).reshape(2)
            if self.ultimo_proximo is not None:
                self.ultimo_proximo=cv2.transform(np.asarray(self.ultimo_proximo,np.float32).reshape(1,1,2),
                                                transformacao).reshape(2)
            self.poligono=poligono_novo.astype(np.float32)
            self.jogador=p_novo.astype(np.float32)
            w,h=self.frame_size
            # Com camera seguidora, parte da cerca naturalmente sai da tela.
            # O poligono permanece valido mesmo quando alguns cantos ficam fora.
            if distancia_cerca(self.poligono,self.jogador) <= margem_segura(w,h)*.70:
                # Continua executando; a proxima rodada ira priorizar o centro.
                if self.medicoes % 15 == 0:
                    mensagem('Proximo da cerca: corrigindo rota para o interior.')
        self.ultima_captura_valida = posterior
        self.medicoes += 1
        if self.medicoes <= 4 or self.medicoes % 20 == 0:
            mensagem(f'Rastreamento {metodo}: confianca {confianca_cenario:.2f}; avatar {confianca_avatar:.2f}; movimento relativo {np.round(relativo,1).tolist()}')
        return relativo.astype(np.float32), (confianca_cenario,confianca_avatar)

    def calibrar(self, sct):
        mensagem('Calibrando W e D. Nao mexa no mouse, zoom ou camera; deixe o personagem no meio.')
        base = self.capturar(sct)
        h, w = base.shape[:2]
        self.frame_size = (w, h)
        if self.area_marcada is None:
            mensagem('SEGURANCA: voce precisa marcar a cerca com F5 antes de iniciar.')
            return False
        poly, jogador, size = self.area_marcada
        if size != (w, h):
            mensagem('SEGURANCA: a janela mudou de tamanho depois da marcação. Aperte F5 e remarque a cerca.')
            return False
        self.poligono = poly.copy()
        self.jogador = jogador.copy()
        if distancia_cerca(self.poligono, self.jogador) < margem_segura(w,h)*2:
            mensagem('SEGURANCA: marque seu avatar mais ao centro do cercado para permitir a calibracao.')
            return False
        # Se o jogo nao estiver focado, nao simular teclas em outro aplicativo.
        dur = .28
        vw, q_w = self.medir_passo(sct, 'w', dur)
        if vw is None: return False
        # Volta para perto da posicao inicial. Mantem a arena atualizada.
        if self.parar_evento.is_set(): return False
        self.medir_passo(sct, 's', dur)
        if self.parar_evento.is_set(): return False
        vd, q_d = self.medir_passo(sct, 'd', dur)
        if vd is None: return False
        if self.parar_evento.is_set(): return False
        self.medir_passo(sct, 'a', dur)
        if self.parar_evento.is_set(): return False
        mensagem(f'W: {np.round(vw,1).tolist()} px / D: {np.round(vd,1).tolist()} px')
        if np.linalg.norm(vw) < 4 or np.linalg.norm(vd) < 4:
            mensagem('ERRO: Um movimento nao foi detectado. Confira o foco, zoom e camera. Algumas versoes do Roblox ignoram teclas simuladas.')
            return False
        matriz = np.column_stack((vw / dur, vd / dur))
        if abs(float(np.linalg.det(matriz))) < 110:
            mensagem('ERRO: Os movimentos nao ficaram independentes; nao consigo calcular uma direcao segura.')
            return False
        self.matriz = matriz
        mensagem('Calibracao concluida. Indo ate as macas...')
        return True

    def achar_alvo(self, macas):
        if not macas:
            return None
        destinos = []
        for f in macas:
            pt = np.array([f['x'], f['y']])
            if any(np.linalg.norm(pt-b) < 36 for b in self.bloqueadas):
                continue
            if distancia_cerca(self.poligono, pt) < max(10.0, MARGEM_FRUTA_REFERENCIA * min(self.frame_size[0]/1128.0, self.frame_size[1]/807.0)):
                continue
            dist = np.linalg.norm(pt-self.jogador)
            destinos.append((float(dist), f))
        if not destinos:
            if len(self.bloqueadas) > 18:
                self.bloqueadas = self.bloqueadas[-10:]
            return None
        destinos.sort(key=lambda item: item[0])
        return destinos[0][1]

    def destino_patrulha(self):
        # Movimento continuo quando nao ha fruta disponivel, longe das bordas.
        # Quatro pontos internos e o centro, em coords do cenario.
        a,b,c,d = self.poligono
        centro = self.poligono.mean(axis=0)
        waypoints = [centro*.55 + ponto*.45 for ponto in (a,b,c,d)]
        waypoints += [centro.copy()]
        este = waypoints[self.patrulha_indice % len(waypoints)].copy()
        if float(np.linalg.norm(self.jogador-este)) < 38:
            self.patrulha_indice += 1
            este = waypoints[self.patrulha_indice % len(waypoints)].copy()
        self.patrulha_alvo = este
        # O alvo e as cercas movem-se juntos, transformacao atualizada em medir_passo.
        return {'x':float(self.patrulha_alvo[0]),'y':float(self.patrulha_alvo[1]),'cor':'patrulha'}

    def escolher_passo_seguro(self, alvo):
        """Prevê o deslocamento relativo da cerca para cada tecla antes de apertá-la.
        Retorna apenas trajetos com margem >= minimo em TODAS as amostras do passo.
        """
        w, h = self.frame_size
        limite = margem_segura(w,h)
        vetor = self.jogador - np.array([alvo['x'], alvo['y']], np.float32)
        tempos = np.linalg.solve(self.matriz, vetor)
        # Comandos apropriados na direcao da fruta, depois avalia ambos eixos.
        candidatos = []
        for eixo in (0, 1):
            t = float(tempos[eixo])
            if abs(t) < .012:
                continue
            tecla = ('w' if t > 0 else 's') if eixo == 0 else ('d' if t > 0 else 'a')
            # V6: passos mais longos (e menos capturas por distancia).
            # PERTO DA CERCA voltamos a passos pequenos automaticamente.
            vel = {1: .14, 2: .24, 3: .31}[self.nivel_velocidade]
            distancia_borda = distancia_cerca(self.poligono,self.jogador)
            if distancia_borda < limite * 2.0:
                vel = min(vel, .095)
            elif distancia_borda < limite * 3.2:
                vel = min(vel, .155)
            dur = float(np.clip(abs(t), .055, vel))
            # Frutas e cerca se deslocam na direcao de matriz*tempo (relativo avatar).
            delta = self.matriz[:, eixo] * np.sign(t) * dur
            minimo = min(distancia_cerca(self.poligono + delta * fator, self.jogador)
                         for fator in (.25, .5, .75, 1.0))
            if minimo < limite:
                # Reduz o passo progressivamente quando chega perto da cerca.
                for fracao in (.75, .5, .3):
                    novo = dur * fracao
                    if novo < .035:
                        break
                    deslocamento = delta * fracao
                    dist = min(distancia_cerca(self.poligono + deslocamento * f, self.jogador)
                               for f in (.25, .5, .75, 1.0))
                    if dist >= limite:
                        dur, minimo, delta = novo, dist, deslocamento
                        break
                if minimo < limite:
                    continue
            reducao = float(np.linalg.norm(vetor) - np.linalg.norm(vetor-delta))
            if reducao > 0:
                candidatos.append((reducao, tecla, dur))
        if not candidatos:
            return None
        candidatos.sort(reverse=True)
        _, tecla, dur = candidatos[0]
        return tecla, dur

    def passo_para_centro(self):
        """Retorna um passo que aumenta margem da cerca sem assumir rastreamento perfeito."""
        if self.matriz is None or self.frame_size is None:
            return None
        dist0=distancia_cerca(self.poligono,self.jogador)
        melhores=[]
        for i in (0,1):
            for sinal,tecla in ((1,('w','d')[i]),(-1,('s','a')[i])):
                segundos=.065
                delta=self.matriz[:,i]*sinal*segundos
                distancias=[distancia_cerca(self.poligono+delta*f,self.jogador)
                            for f in (.25,.5,.75,1.)]
                if min(distancias) >= dist0-1.5 and distancias[-1] > dist0+2.:
                    melhores.append((distancias[-1], tecla, segundos))
        if not melhores:
            return None
        _, tecla, segundos = max(melhores)
        return tecla, segundos

    def executar(self):
        tentativas_sem_movimento = 0
        self.bloqueadas.clear()
        self.medicoes = 0
        self.patrulha_indice = 0
        self.patrulha_alvo = None
        try:
            self.hwnd = self.encontrar_janela()
            # Permite usar "7 + Enter" no terminal e depois voltar ao jogo.
            if not self.jogo_em_foco():
                mensagem('Aguardando o Roblox receber foco. Clique no jogo em ate 20 segundos...')
                limite = time.monotonic() + 20
                while not self.parar_evento.is_set() and not self.jogo_em_foco():
                    if time.monotonic() >= limite:
                        mensagem('Nao consegui focar o Roblox. Digite 7 novamente e clique no jogo.')
                        return
                    time.sleep(.15)
            if self.parar_evento.is_set():
                return
            mensagem('Roblox em foco. Iniciando calibracao...')
            with mss.MSS() as sct:
                if not self.calibrar(sct):
                    return
                while not self.parar_evento.is_set():
                    if self.pausar_evento.is_set():
                        self.liberar_teclas()
                        time.sleep(.12)
                        continue
                    if not self.jogo_em_foco():
                        self.liberar_teclas()
                        time.sleep(.25)
                        continue
                    frame = self.capturar(sct)
                    macas = reconhecer_macas(frame, self.poligono)
                    alvo = self.achar_alvo(macas) if macas else None
                    if alvo is None:
                        alvo = self.destino_patrulha()
                        if self.medicoes % 25 == 0:
                            mensagem('Sem macas acessiveis; patrulhando o interior da cerca...')
                    else:
                        self.patrulha_alvo = None
                    pt = np.array([alvo['x'], alvo['y']], np.float32)
                    distancia = float(np.linalg.norm(pt-self.jogador))
                    if distancia < 22:
                        if alvo['cor'] == 'patrulha':
                            self.patrulha_indice += 1
                            self.patrulha_alvo = None
                            time.sleep(.08)
                            continue
                        # Se uma maca nao desaparece apos o avatar chegar, nao ficar preso nela.
                        if self.ultimo_proximo is not None and np.linalg.norm(pt-self.ultimo_proximo) < 25:
                            self.contagem_proximo += 1
                        else:
                            self.contagem_proximo = 1
                        self.ultimo_proximo = pt.copy()
                        if self.contagem_proximo >= 9:
                            self.bloqueadas.append(pt.copy())
                            self.contagem_proximo = 0
                        time.sleep(.18)
                        continue
                    else:
                        self.contagem_proximo = 0
                    limite_borda = margem_segura(*self.frame_size)
                    if distancia_cerca(self.poligono,self.jogador) < limite_borda * 1.35:
                        # Ignora frutas junto a madeira e busca o centro da arena.
                        c = self.poligono.mean(axis=0)
                        alvo={'x':float(c[0]),'y':float(c[1]),'cor':'retorno ao centro'}
                    passo = self.escolher_passo_seguro(alvo)
                    if passo is None and distancia_cerca(self.poligono,self.jogador) < limite_borda*1.35:
                        passo = self.passo_para_centro()
                    if passo is None:
                        if time.monotonic()-self.ultimo_aguardo > 5:
                            mensagem('Sem trajeto seguro agora. Recalculando sem encerrar a sessao.')
                            self.ultimo_aguardo = time.monotonic()
                        if alvo['cor'] == 'patrulha':
                            self.patrulha_indice += 1
                        else:
                            self.bloqueadas.append(pt.copy())
                        time.sleep(.09)
                        continue
                    tecla, segundos = passo
                    relativo, _ = self.medir_passo(sct, tecla, segundos)
                    if relativo is None:
                        if self.parar_evento.is_set(): break
                        # Conservar a sessao ativa e readquirir referencias;
                        # nao exigir F9 nem um novo F7 do usuario.
                        try:
                            self.recuperar_sem_mover(sct)
                        except Exception as rec_e:
                            if time.monotonic()-self.ultimo_aguardo > 8:
                                mensagem(f'Recuperacao em andamento: {rec_e}')
                                self.ultimo_aguardo = time.monotonic()
                        time.sleep(.08)
                        continue
                    if np.linalg.norm(relativo) < 1.8:
                        tentativas_sem_movimento += 1
                        if tentativas_sem_movimento >= 10:
                            mensagem('Personagem parece bloqueado; mudando a rota, sem encerrar o coletor.')
                            if alvo['cor'] == 'patrulha':
                                self.patrulha_indice += 1
                            else:
                                self.bloqueadas.append(pt.copy())
                            tentativas_sem_movimento = 0
                    else:
                        tentativas_sem_movimento = 0
                    if self.ultimo_alvo is not None and np.linalg.norm(pt-self.ultimo_alvo) < 33:
                        self.passos_alvo += 1
                    else:
                        self.passos_alvo = 1
                    self.ultimo_alvo = pt
                    if self.passos_alvo >= 26:
                        mensagem('Alvo dificil de alcancar, procurando outro.')
                        if alvo['cor'] == 'patrulha':
                            self.patrulha_indice += 1
                            self.patrulha_alvo = None
                        else:
                            self.bloqueadas.append(pt.copy())
                        self.passos_alvo = 0
                    if self.passos_alvo % 12 == 1:
                        mensagem(f'{len(macas)} macas visiveis | alvo {alvo["cor"]} a {distancia:.0f}px | tecla {tecla.upper()} {segundos:.2f}s')
                    if self.medicoes % 20 == 0:
                        try:
                            agora = self.capturar(sct)
                            atuais = reconhecer_macas(agora, self.poligono)
                            cv2.imwrite(str(BASE_DIR/'coleta_em_andamento.png'),
                                imagem_marcada(agora, self.poligono, self.jogador, atuais, alvo))
                        except Exception:
                            pass
        except Exception as e:
            mensagem(f'ERRO de execucao: {e}')
            traceback.print_exc()
        finally:
            self.liberar_teclas()
            mensagem('Sessao encerrada; teclas liberadas.')

    def iniciar(self):
        mensagem('Pedido de inicio recebido.')
        if self.calibrando_area:
            mensagem('Termine a marcacao de F5 primeiro.')
            return
        if self.area_marcada is None:
            mensagem('SEGURANCA: antes de iniciar, aperte F5 para selecionar a cerca e seu personagem!')
            return
        if self.thread is not None and self.thread.is_alive():
            mensagem('Ja esta executando. Use F9 para pausar/retomar.')
            return
        try:
            self.hwnd = self.encontrar_janela()
        except Exception as e:
            mensagem(f'Nao consegui iniciar: {e}')
            return
        self.parar_evento.clear()
        self.pausar_evento.clear()
        self.frame_size = None  # permite reiniciar apos mudar o tamanho do jogo
        self.poligono = None
        self.jogador = None
        self.matriz = None
        self.ultimo_alvo = None
        self.passos_alvo = 0
        self.patrulha_indice = 0
        self.patrulha_alvo = None
        self.passo_modelado = 0
        self.falhas_rastreamento = 0
        self.ultima_captura_valida = None
        self.falha_passo = None
        self.thread = threading.Thread(target=self.executar, daemon=True)
        self.thread.start()

    def parar(self):
        self.parar_evento.set()
        self.liberar_teclas()
        mensagem('F8 pressionado: parando.')

    def pausar(self):
        if self.thread is None or not self.thread.is_alive():
            return
        if self.pausar_evento.is_set():
            self.pausar_evento.clear()
            mensagem('Retomando coleta.')
        else:
            self.pausar_evento.set()
            self.liberar_teclas()
            mensagem('Coleta pausada. F9 para continuar.')

    def salvar_imagem(self):
        try:
            hwnd_atual = self.encontrar_janela()
            anterior_h = self.hwnd
            self.hwnd = hwnd_atual
            with mss.MSS() as sct:
                frame = self.capturar(sct)
            self.hwnd = anterior_h
            h, w = frame.shape[:2]
            if self.poligono is not None and self.frame_size == (w,h):
                poly = self.poligono.copy()
                jogador = self.jogador.copy()
            elif self.area_marcada is not None and self.area_marcada[2] == (w,h):
                poly, jogador, _ = self.area_marcada
            else:
                mensagem('F6: primeiro selecione a cerca com F5.')
                return
            macas = reconhecer_macas(frame, poly)
            saida = BASE_DIR / 'deteccao_macas.png'
            cv2.imwrite(str(saida), imagem_marcada(frame, poly, jogador, macas))
            mensagem(f'F6: {len(macas)} macas detectadas. Imagem salva em: {saida}')
        except Exception as e:
            mensagem(f'Nao consegui salvar diagnostico: {e}')


def main():
    parser = argparse.ArgumentParser(description='Identificador e coletor de macas no Roblox')
    parser.add_argument('--teste', metavar='IMAGEM', help='Apenas reconhece as macas de uma captura PNG/JPG')
    argumentos = parser.parse_args()
    if argumentos.teste:
        teste_offline(argumentos.teste)
        return
    if sys.platform != 'win32':
        sys.exit('A automacao ao vivo requer Windows; use --teste para testar imagens.')
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()  # evita coordenadas deslocadas em telas com escala > 100%
    except Exception:
        pass
    bot = Bot()
    print('\n======== COLETOR DE MACAS / ROBLOX (VERSAO 6: COLETA CONTINUA + RECUPERACAO) ========')
    print('Coleta continua com auto-recuperacao. Perda de rastreamento nao ativa F9.')
    print('Velocidade 1 NORMAL, 2 RAPIDA (padrao), 3 TURBO: digite no CMD e ENTER.')
    print('F5 = marcar 4 cantos internos da cerca e o SEU avatar.')
    print('Marque F5 uma vez; mantenha zoom e camera estaveis. F8 para parar; F9 para pausa.')
    print('Atalhos: F5 = marcar cerca | F6 = foto | F7 = iniciar | F8 = parar | F9 = pausa')
    print('SE F7 NAO FUNCIONAR: clique NESTA janela, digite 7 e aperte ENTER.')
    print('Depois clique no Roblox em ate 20 segundos.\n')
    atalhos = {'f5': bot.marcar_cerca, 'f6': bot.salvar_imagem, 'f7': bot.iniciar,
               'f8': bot.parar, 'f9': bot.pausar}
    for tecla, acao in atalhos.items():
        try:
            # No Windows, observar a tecla pressionada e mais confiavel do que
            # esperar o evento "soltar tecla" em certos jogos.
            keyboard.add_hotkey(tecla, acao, suppress=False, trigger_on_release=False)
            mensagem(f'Atalho {tecla.upper()} registrado.')
        except Exception as e:
            mensagem(f'Nao consegui registrar {tecla.upper()}: {e}. Use o menu numerico.')
    print('\nMENU: 5=cerca, 7=iniciar, 6=foto, 8=parar, 9=pausar, 1/2/3=velocidade, 0=sair')
    try:
        while True:
            try:
                comando = input('Digite um comando e pressione ENTER: ').strip().lower()
            except EOFError:
                break
            if comando == '5':
                bot.marcar_cerca()
            elif comando == '7':
                bot.iniciar()
            elif comando == '6':
                bot.salvar_imagem()
            elif comando == '8':
                bot.parar()
            elif comando == '9':
                bot.pausar()
            elif comando in ('1','2','3'):
                bot.mudar_velocidade(int(comando))
            elif comando == '0':
                break
            elif comando:
                print('Comando nao reconhecido. Use 5, 6, 7, 8, 9, 1, 2, 3 ou 0.')
    except KeyboardInterrupt:
        pass
    finally:
        bot.parar()
        if bot.thread and bot.thread.is_alive():
            bot.thread.join(timeout=1)
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        print('Fechado.')


if __name__ == '__main__':
    main()
