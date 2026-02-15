export class ModalWebRtcClient extends EventTarget {
    constructor() {
        super();
        this.ws = null;
        this.localStream = null;
        this.peerConnection = null;
        this.dataChannel = null;
        this.iceServers = null;
        this.peerID = null;
    }

    log(message) {
        this.dispatchEvent(new CustomEvent('status', { detail: { message } }));
        console.log(message);
    }

    async startWebcam() {
        this.localStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: "environment" }, width: 640, height: 480 },
            audio: false,
        });
        this.dispatchEvent(new CustomEvent('localStream', {
            detail: { stream: this.localStream },
        }));
        return this.localStream;
    }

    async startStreaming() {
        this.peerID = this._uuid();
        this.log('Connecting to GPU tracker...');
        await this._negotiate();
    }

    async _negotiate() {
        this.ws = new WebSocket(`/ws/${this.peerID}`);

        this.ws.onerror = (e) => {
            this.dispatchEvent(new CustomEvent('error', { detail: { error: e } }));
        };
        this.ws.onclose = () => {
            this.dispatchEvent(new CustomEvent('websocketClosed'));
        };
        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'answer') {
                this.log('Got SDP answer, connecting...');
                this.peerConnection.setRemoteDescription(msg);
            } else if (msg.type === 'turn_servers') {
                this.iceServers = msg.ice_servers;
            }
        };

        await new Promise((resolve) => {
            if (this.ws.readyState === WebSocket.OPEN) resolve();
            else this.ws.addEventListener('open', () => resolve(), { once: true });
        });

        this.iceServers = [{ urls: ["stun:stun.l.google.com:19302"] }];

        this.peerConnection = new RTCPeerConnection({ iceServers: this.iceServers });

        // Create data channel for coordinates BEFORE creating offer
        this.dataChannel = this.peerConnection.createDataChannel("coordinates", {
            ordered: false,       // don't need ordering, just latest data
            maxRetransmits: 0,    // drop old data, keep latency low
        });

        this.dataChannel.onopen = () => {
            this.log('Data channel open — coordinates streaming');
            this.dispatchEvent(new CustomEvent('dataChannelOpen'));
        };

        this.dataChannel.onmessage = (event) => {
            this.dispatchEvent(new CustomEvent('coordinates', {
                detail: JSON.parse(event.data),
            }));
        };

        this.dataChannel.onclose = () => {
            this.dispatchEvent(new CustomEvent('dataChannelClosed'));
        };

        // Add video track
        this.localStream.getTracks().forEach((track) => {
            this.peerConnection.addTrack(track, this.localStream);
        });

        // Receive annotated video back
        this.peerConnection.ontrack = (event) => {
            this.dispatchEvent(new CustomEvent('remoteStream', {
                detail: { stream: event.streams[0] },
            }));
        };

        // Trickle ICE
        this.peerConnection.onicecandidate = (event) => {
            if (!event.candidate?.candidate) return;
            this.ws.send(JSON.stringify({
                type: 'ice_candidate',
                candidate: {
                    peer_id: this.peerID,
                    candidate_sdp: event.candidate.candidate,
                    sdpMid: event.candidate.sdpMid,
                    sdpMLineIndex: event.candidate.sdpMLineIndex,
                    usernameFragment: event.candidate.usernameFragment,
                },
            }));
        };

        this.peerConnection.onconnectionstatechange = () => {
            const state = this.peerConnection.connectionState;
            this.log(`WebRTC: ${state}`);
            this.dispatchEvent(new CustomEvent('connectionStateChange', {
                detail: { state },
            }));
            if (state === 'connected' && this.ws.readyState === WebSocket.OPEN) {
                this.ws.close();
            }
        };

        // Create and send offer
        await this.peerConnection.setLocalDescription();
        this.ws.send(JSON.stringify({
            peer_id: this.peerID,
            type: 'offer',
            sdp: this.peerConnection.localDescription.sdp,
        }));
    }

    async stop() {
        if (this.dataChannel) { this.dataChannel.close(); this.dataChannel = null; }
        if (this.peerConnection) { await this.peerConnection.close(); this.peerConnection = null; }
        if (this.ws && this.ws.readyState === WebSocket.OPEN) { this.ws.close(); this.ws = null; }
        this.iceServers = null;
        this.dispatchEvent(new CustomEvent('stopped'));
    }

    _uuid() {
        const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
        let r = '';
        for (let i = 0; i < 22; i++) r += c[Math.floor(Math.random() * c.length)];
        return r;
    }
}
