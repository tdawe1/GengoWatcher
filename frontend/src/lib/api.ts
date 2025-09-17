import { QueryClient } from '@tanstack/react-query';

// API Configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8001`;

// Create query client instance
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      staleTime: 5 * 60 * 1000, // 5 minutes
      gcTime: 10 * 60 * 1000, // 10 minutes
    },
  },
});

// Types
export interface Job {
  id: string;
  title: string;
  description: string;
  reward: number;
  currency: string;
  url: string;
  timestamp: string;
  source: 'websocket' | 'rss';
}

export interface WatcherStatus {
  is_running: boolean;
  websocket_status: string;
  rss_status: string;
  last_check_time: number | null;
  next_check_time: number;
  session_stats: {
    new_entries: number;
    total_value: number;
    uptime: number;
  };
  failure_count: number;
}



export interface ConfigSection {
  [key: string]: string | number | boolean;
}

export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface Stats {
  total_jobs: number;
  jobs_today: number;
  websocket_connections: number;
  rss_checks: number;
  last_job_timestamp: string | null;
  total_value?: number;
  average_reward?: number;
  jobs_by_source?: Record<string, number>;
  session_stats?: {
    new_entries: number;
    total_value: number;
  };
  uptime?: number;
}

// API Client Class
class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
  }

  private getHeaders(): HeadersInit {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    return headers;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    const url = `${API_BASE_URL}${endpoint}`;

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          ...this.getHeaders(),
          ...options.headers,
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      return data;
    } catch (error) {
      console.error(`API request failed: ${endpoint}`, error);
      throw error;
    }
  }

  // Health check (public)
  async health(): Promise<ApiResponse<{ status: string; timestamp: string }>> {
    return this.request('/api/status');
  }

  // Status (authenticated)
  async getStatus(): Promise<ApiResponse<WatcherStatus>> {
    return this.request('/api/status');
  }

  // Jobs (authenticated)
  async getJobs(params: {
    page?: number;
    page_size?: number;
    source?: 'websocket' | 'rss';
    min_reward?: number;
    max_reward?: number;
  } = {}): Promise<ApiResponse<PaginatedResponse<Job>>> {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.append(key, value.toString());
      }
    });

    const query = searchParams.toString();
    return this.request(`/api/jobs${query ? `?${query}` : ''}`);
  }

  // Config (authenticated)
  async getConfig(): Promise<ApiResponse<Record<string, ConfigSection>>> {
    return this.request('/api/config');
  }

  async updateConfig(
    section: string,
    option: string,
    value: string | number | boolean
  ): Promise<ApiResponse<{ success: boolean }>> {
    return this.request('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ section, option, value }),
    });
  }

  // Commands (authenticated)
  async executeCommand(command: string): Promise<ApiResponse<{ output: string }>> {
    return this.request('/api/commands', {
      method: 'POST',
      body: JSON.stringify({ command }),
    });
  }

  // Stats (authenticated)
  async getStats(): Promise<ApiResponse<Stats>> {
    return this.request('/api/stats');
  }
}

// Export singleton instance
export const apiClient = new ApiClient();

// WebSocket connection for real-time updates
export class StatusWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000; // Start with 1 second
  private token: string | null = null;

  private onMessage: (data: WatcherStatus) => void;
  private onError: (error: Event) => void;
  private onClose: () => void;

  constructor(
    onMessage: (data: WatcherStatus) => void,
    onError: (error: Event) => void,
    onClose: () => void
  ) {
    this.onMessage = onMessage;
    this.onError = onError;
    this.onClose = onClose;
  }

  setToken(token: string) {
    this.token = token;
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/status`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;

        // Send authentication if token is available
        if (this.token) {
          this.ws?.send(JSON.stringify({ token: this.token }));
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.onMessage(data);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.onError(error);
      };

      this.ws.onclose = () => {
        console.log('WebSocket closed');
        this.onClose();
        this.attemptReconnect();
      };
    } catch (error) {
      console.error('Failed to create WebSocket connection:', error);
      this.attemptReconnect();
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max WebSocket reconnection attempts reached');
      return;
    }

    this.reconnectAttempts++;
    console.log(`Attempting WebSocket reconnection ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${this.reconnectDelay}ms`);

    setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 16000); // Exponential backoff, max 16 seconds
      this.connect();
    }, this.reconnectDelay);
  }
}