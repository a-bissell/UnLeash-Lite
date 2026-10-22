import { getToken } from './client';

type MessageHandler = (data: any) => void;

export class FleetSocket {
  private ws: WebSocket | null = null;
  private handlers: MessageHandler[] = [];
  private reconnectTimer: number | null = null;

  connect(path: string) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = getToken();
    const qs = token ? `?token=${encodeURIComponent(token)}` : '';
    const url = `${proto}//${window.location.host}${path}${qs}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handlers.forEach((h) => h(data));
      } catch {}
    };

    this.ws.onclose = () => {
      this.reconnectTimer = window.setTimeout(() => this.connect(path), 3000);
    };
  }

  onMessage(handler: MessageHandler) {
    this.handlers.push(handler);
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}
