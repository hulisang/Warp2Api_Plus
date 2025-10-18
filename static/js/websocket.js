/**
 * WebSocket管理器
 * 负责与后端/ws端点建立连接，接收并处理实时数据包
 */

class WebSocketManager {
    constructor() {
        this.ws = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 3000; // 3秒
        this.packets = []; // 存储所有数据包
        this.maxPackets = 100; // 最多保存100条
        
        // 统计数据
        this.stats = {
            totalPackets: 0,
            requestCount: 0,
            responseCount: 0,
            totalSize: 0
        };
        
        // 当前过滤类型
        this.filterType = 'all';
        
        // 自动滚动开关
        this.autoScroll = true;
    }
    
    /**
     * 连接WebSocket
     */
    connect() {
        // 获取当前URL的协议和主机
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws`;
        
        console.log(`连接WebSocket: ${wsUrl}`);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            // 连接打开
            this.ws.onopen = () => {
                console.log('✅ WebSocket连接成功');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
                this.showNotification('WebSocket连接成功', 'success');
            };
            
            // 接收消息
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (error) {
                    console.error('消息解析失败:', error);
                }
            };
            
            // 连接关闭
            this.ws.onclose = () => {
                console.log('❌ WebSocket连接关闭');
                this.isConnected = false;
                this.updateConnectionStatus(false);
                this.attemptReconnect();
            };
            
            // 连接错误
            this.ws.onerror = (error) => {
                console.error('WebSocket错误:', error);
                this.showNotification('WebSocket连接错误', 'error');
            };
            
        } catch (error) {
            console.error('创建WebSocket失败:', error);
            this.showNotification('无法创建WebSocket连接', 'error');
        }
    }
    
    /**
     * 断开连接
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.isConnected = false;
        this.updateConnectionStatus(false);
    }
    
    /**
     * 尝试重新连接
     */
    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`尝试重新连接... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            
            setTimeout(() => {
                this.connect();
            }, this.reconnectDelay);
        } else {
            console.error('达到最大重连次数，停止重连');
            this.showNotification('连接失败，请手动重新连接', 'error');
        }
    }
    
    /**
     * 处理接收到的消息
     */
    handleMessage(data) {
        console.log('收到消息:', data);
        
        const { event, packet, message, timestamp } = data;
        
        // 处理不同事件类型
        switch (event) {
            case 'connected':
                console.log('服务器确认连接:', message);
                break;
                
            case 'packet_history':
                // 历史数据包
                this.addPacket(packet);
                break;
                
            case 'packet_captured':
                // 新捕获的数据包
                this.addPacket(packet);
                this.updateStats(packet);
                break;
                
            case 'stream_chunk_parsed':
                // 流式解析事件
                this.addStreamEvent('chunk_parsed', data);
                break;
                
            case 'stream_chunk_error':
                // 流式错误
                this.addStreamEvent('chunk_error', data);
                break;
                
            case 'stream_completed':
                // 流式完成
                this.addStreamEvent('completed', data);
                break;
                
            default:
                console.log('未知事件类型:', event);
        }
    }
    
    /**
     * 添加数据包
     */
    addPacket(packet) {
        // 添加到数组开头（最新的在最前）
        this.packets.unshift(packet);
        
        // 限制数组大小
        if (this.packets.length > this.maxPackets) {
            this.packets.pop();
        }
        
        // 渲染到页面
        this.renderPacket(packet);
    }
    
    /**
     * 添加流式事件
     */
    addStreamEvent(type, data) {
        // 计算事件大小：优先使用聚合结果中的 total_event_bytes，其次使用分片大小
        let sizeBytes = 0;
        try {
            if (type === 'completed' && data && data.result && typeof data.result.total_event_bytes === 'number') {
                sizeBytes = data.result.total_event_bytes;
            } else if (type === 'chunk_parsed' && data && data.chunk && typeof data.chunk.size === 'number') {
                sizeBytes = data.chunk.size;
            }
        } catch (_) {}

        // 选择更贴切的时间戳
        const ts = (data && data.timestamp)
            || (data && data.result && data.result.timestamp)
            || new Date().toISOString();

        const eventPacket = {
            timestamp: ts,
            type: `stream_${type}`,
            size: sizeBytes,
            data_preview: `流式处理事件: ${type}`,
            full_data: data
        };
        
        this.addPacket(eventPacket);
    }
    
    /**
     * 更新统计数据
     */
    updateStats(packet) {
        this.stats.totalPackets++;
        
        if (packet.type === 'request') {
            this.stats.requestCount++;
        } else if (packet.type === 'response') {
            this.stats.responseCount++;
        }
        
        this.stats.totalSize += packet.size || 0;
        
        // 更新页面显示
        this.updateStatsDisplay();
    }
    
    /**
     * 更新统计显示
     */
    updateStatsDisplay() {
        document.getElementById('total-packets').textContent = this.stats.totalPackets;
        document.getElementById('request-count').textContent = this.stats.requestCount;
        document.getElementById('response-count').textContent = this.stats.responseCount;
        
        const sizeInKB = (this.stats.totalSize / 1024).toFixed(2);
        document.getElementById('total-size').textContent = `${sizeInKB} KB`;
    }
    
    /**
     * 渲染数据包到页面
     */
    renderPacket(packet) {
        const container = document.getElementById('log-container');
        
        // 移除空状态
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }
        
        // 检查过滤条件
        if (!this.shouldShowPacket(packet)) {
            return;
        }
        
        // 创建日志项
        const logItem = document.createElement('div');
        logItem.className = 'log-item';
        logItem.dataset.packetType = packet.type || 'unknown';
        
        // 格式化时间
        const time = new Date(packet.timestamp).toLocaleTimeString('zh-CN');
        
        // 格式化大小
        const size = packet.size ? `${packet.size} B` : 'N/A';
        
        // 获取类型标签
        const typeLabel = this.getTypeLabel(packet.type);
        
        logItem.innerHTML = `
            <div class="log-header">
                <div class="log-type">${typeLabel}</div>
                <div class="log-meta">
                    <span class="log-time">⏰ ${time}</span>
                    <span class="log-size">📦 ${size}</span>
                </div>
            </div>
            <div class="log-body">
                <div class="log-preview">${this.escapeHtml(packet.data_preview || '无预览')}</div>
                <div class="log-actions">
                    <button class="log-btn" onclick="wsManager.showPacketDetails(${this.packets.indexOf(packet)})">
                        查看完整数据
                    </button>
                </div>
            </div>
        `;
        
        // 点击头部展开/折叠
        const header = logItem.querySelector('.log-header');
        header.addEventListener('click', () => {
            logItem.classList.toggle('expanded');
        });
        
        // 插入到容器开头
        container.insertBefore(logItem, container.firstChild);
        
        // 自动滚动到顶部
        if (this.autoScroll) {
            container.scrollTop = 0;
        }
    }
    
    /**
     * 检查是否应该显示该数据包
     */
    shouldShowPacket(packet) {
        if (this.filterType === 'all') {
            return true;
        }
        
        // 处理流式事件类型
        if (packet.type && packet.type.startsWith('stream_')) {
            return this.filterType === packet.type || this.filterType === 'stream_all';
        }
        
        return packet.type === this.filterType;
    }
    
    /**
     * 获取类型标签
     */
    getTypeLabel(type) {
        const labels = {
            'request': '📤 请求',
            'response': '📥 响应',
            'stream_chunk_parsed': '🔄 流式解析',
            'stream_chunk_error': '❌ 流式错误',
            'stream_completed': '✅ 流式完成',
            'packet_captured': '📦 数据包捕获',
            'connected': '🔌 连接事件'
        };
        
        return labels[type] || '❓ 未知';
    }
    
    /**
     * 显示数据包详情
     */
    showPacketDetails(index) {
        const packet = this.packets[index];
        if (!packet) {
            return;
        }
        
        const modal = document.getElementById('packet-modal');
        const modalBody = document.getElementById('modal-body');
        
        // 格式化JSON
        const jsonStr = JSON.stringify(packet.full_data || packet, null, 2);
        
        modalBody.innerHTML = `
            <div class="packet-info">
                <h4>基本信息</h4>
                <p><strong>类型:</strong> ${this.getTypeLabel(packet.type)}</p>
                <p><strong>时间:</strong> ${new Date(packet.timestamp).toLocaleString('zh-CN')}</p>
                <p><strong>大小:</strong> ${packet.size || 0} 字节</p>
            </div>
            <div class="packet-data">
                <h4>完整数据</h4>
                <pre>${this.escapeHtml(jsonStr)}</pre>
            </div>
        `;
        
        modal.classList.add('active');
    }
    
    /**
     * 关闭详情弹窗
     */
    closeModal() {
        const modal = document.getElementById('packet-modal');
        modal.classList.remove('active');
    }
    
    /**
     * 清空历史记录
     */
    clearHistory() {
        this.packets = [];
        this.stats = {
            totalPackets: 0,
            requestCount: 0,
            responseCount: 0,
            totalSize: 0
        };
        
        const container = document.getElementById('log-container');
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <div class="empty-text">历史记录已清空</div>
                <div class="empty-hint">等待新的数据包...</div>
            </div>
        `;
        
        this.updateStatsDisplay();
        this.showNotification('历史记录已清空', 'success');
    }
    
    /**
     * 设置过滤类型
     */
    setFilter(type) {
        this.filterType = type;
        this.reRenderAll();
    }
    
    /**
     * 重新渲染所有数据包
     */
    reRenderAll() {
        const container = document.getElementById('log-container');
        container.innerHTML = '';
        
        // 反向遍历（从旧到新）
        for (let i = this.packets.length - 1; i >= 0; i--) {
            this.renderPacket(this.packets[i]);
        }
        
        if (container.children.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🔍</div>
                    <div class="empty-text">没有符合条件的数据包</div>
                    <div class="empty-hint">尝试更改过滤条件</div>
                </div>
            `;
        }
    }
    
    /**
     * 更新连接状态显示
     */
    updateConnectionStatus(connected) {
        const statusBadge = document.getElementById('ws-status');
        const statusText = statusBadge.querySelector('.status-text');
        
        if (connected) {
            statusBadge.classList.remove('disconnected');
            statusBadge.classList.add('connected');
            statusText.textContent = '已连接';
        } else {
            statusBadge.classList.remove('connected');
            statusBadge.classList.add('disconnected');
            statusText.textContent = '未连接';
        }
    }
    
    /**
     * 显示通知
     */
    showNotification(message, type = 'info') {
        console.log(`[${type.toUpperCase()}] ${message}`);
        // 可以在这里添加更好的通知UI
    }
    
    /**
     * HTML转义
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 创建全局实例
const wsManager = new WebSocketManager();
