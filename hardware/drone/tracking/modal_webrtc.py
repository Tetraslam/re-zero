# Vendored from Modal's WebRTC example (modal-labs/modal-examples)
# https://github.com/modal-labs/modal-examples/tree/main/07_web_endpoints/webrtc

import asyncio
import json
import queue
from abc import ABC, abstractmethod
from typing import Optional

import modal
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketState


class ModalWebRtcPeer(ABC):
    @modal.enter()
    async def _initialize(self):
        import shortuuid

        self.id = shortuuid.uuid()
        self.pcs = {}
        self.pending_candidates = {}
        await self.initialize()

    async def initialize(self):
        pass

    @abstractmethod
    async def setup_streams(self, peer_id):
        raise NotImplementedError

    async def run_streams(self, peer_id):
        pass

    async def get_turn_servers(self, peer_id=None, msg=None) -> Optional[list]:
        pass

    async def _setup_peer_connection(self, peer_id):
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection

        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]
        )
        self.pcs[peer_id] = RTCPeerConnection(configuration=config)
        self.pending_candidates[peer_id] = []
        await self.setup_streams(peer_id)

    @modal.method()
    async def run(self, q: modal.Queue, peer_id: str):
        await self._connect_over_queue(q, peer_id)
        await self._run_streams(peer_id)

    async def _connect_over_queue(self, q, peer_id):
        msg_handlers = {
            "offer": self.handle_offer,
            "ice_candidate": self.handle_ice_candidate,
            "identify": self.get_identity,
            "get_turn_servers": self.get_turn_servers,
        }
        while True:
            try:
                if self.pcs.get(peer_id) and (
                    self.pcs[peer_id].connectionState
                    in ["connected", "closed", "failed"]
                ):
                    q.put("close", partition="server")
                    break
                msg = json.loads(await q.get.aio(partition=peer_id, timeout=0.5))
                if handler := msg_handlers.get(msg.get("type")):
                    response = await handler(peer_id, msg)
                else:
                    response = None
                if response is not None:
                    await q.put.aio(json.dumps(response), partition="server")
            except queue.Empty:
                pass
            except Exception as e:
                print(f"{self.id}: Error: {type(e)}: {e}")
                continue

    async def _run_streams(self, peer_id):
        await self.run_streams(peer_id)
        while self.pcs[peer_id].connectionState == "connected":
            await asyncio.sleep(0.1)

    async def handle_offer(self, peer_id, msg):
        from aiortc import RTCSessionDescription

        await self._setup_peer_connection(peer_id)
        await self.pcs[peer_id].setRemoteDescription(
            RTCSessionDescription(msg["sdp"], msg["type"])
        )
        answer = await self.pcs[peer_id].createAnswer()
        await self.pcs[peer_id].setLocalDescription(answer)
        sdp = self.pcs[peer_id].localDescription.sdp
        return {"sdp": sdp, "type": answer.type, "peer_id": self.id}

    async def handle_ice_candidate(self, peer_id, msg):
        from aiortc.sdp import candidate_from_sdp

        candidate = msg.get("candidate")
        if not candidate:
            raise ValueError
        ice_candidate = candidate_from_sdp(candidate["candidate_sdp"])
        ice_candidate.sdpMid = candidate["sdpMid"]
        ice_candidate.sdpMLineIndex = candidate["sdpMLineIndex"]
        if not self.pcs.get(peer_id):
            self.pending_candidates[peer_id].append(ice_candidate)
        else:
            for c in self.pending_candidates[peer_id]:
                await self.pcs[peer_id].addIceCandidate(c)
            self.pending_candidates[peer_id] = []
            await self.pcs[peer_id].addIceCandidate(ice_candidate)

    async def get_identity(self, peer_id=None, msg=None):
        return {"type": "identify", "peer_id": self.id}

    @modal.exit()
    async def _exit(self):
        await self.exit()
        if self.pcs:
            await asyncio.gather(*[pc.close() for pc in self.pcs.values()])
            self.pcs = {}

    async def exit(self):
        pass


class ModalWebRtcSignalingServer:
    @modal.enter()
    def _initialize(self):
        self.web_app = FastAPI()

        @self.web_app.websocket("/ws/{peer_id}")
        async def ws(client_websocket: WebSocket, peer_id: str):
            try:
                await client_websocket.accept()
                await self._mediate_negotiation(client_websocket, peer_id)
            except Exception as e:
                print(f"Server: WS error from {peer_id}: {type(e)}: {e}")
                await client_websocket.close()

        self.initialize()

    def initialize(self):
        pass

    @abstractmethod
    def get_modal_peer_class(self) -> type[ModalWebRtcPeer]:
        raise NotImplementedError

    @modal.asgi_app()
    def web(self):
        return self.web_app

    async def _mediate_negotiation(self, websocket: WebSocket, peer_id: str):
        modal_peer_class = self.get_modal_peer_class()
        with modal.Queue.ephemeral() as q:
            modal_peer = modal_peer_class()
            modal_peer.run.spawn(q, peer_id)
            await asyncio.gather(
                relay_websocket_to_queue(websocket, q, peer_id),
                relay_queue_to_websocket(websocket, q, peer_id),
            )


async def relay_websocket_to_queue(websocket, q, peer_id):
    while True:
        try:
            msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
            await q.put.aio(msg, partition=peer_id)
        except asyncio.TimeoutError:
            pass
        except Exception:
            if WebSocketState.DISCONNECTED in [
                websocket.application_state,
                websocket.client_state,
            ]:
                return


async def relay_queue_to_websocket(websocket, q, peer_id):
    while True:
        try:
            msg = await q.get.aio(partition="server", timeout=0.5)
            if msg.startswith("close"):
                await websocket.close()
                return
            await websocket.send_text(msg)
        except queue.Empty:
            pass
        except Exception:
            if WebSocketState.DISCONNECTED in [
                websocket.application_state,
                websocket.client_state,
            ]:
                return
