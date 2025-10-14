/**
 * 主JavaScript文件
 * 处理页面交互和UI控制
 */

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Warp2Api+ 实时监控界面启动');
    
    initializeControls();
    initializeTimeDisplay();
    
    // 自动连接WebSocket
    console.log('🔌 自动连接WebSocket...');
    wsManager.connect();
    
    // 更新按钮状态
    const connectBtn = document.getElementById('connect-btn');
    connectBtn.querySelector('.btn-text').textContent = '断开连接';
    connectBtn.querySelector('.btn-icon').textContent = '🔓';
});

/**
 * 初始化控制面板
 */
function initializeControls() {
    // 连接按钮
    const connectBtn = document.getElementById('connect-btn');
    connectBtn.addEventListener('click', () => {
        if (wsManager.isConnected) {
            wsManager.disconnect();
            connectBtn.querySelector('.btn-text').textContent = '连接监控';
            connectBtn.querySelector('.btn-icon').textContent = '🔌';
        } else {
            wsManager.connect();
            connectBtn.querySelector('.btn-text').textContent = '断开连接';
            connectBtn.querySelector('.btn-icon').textContent = '🔓';
        }
    });
    
    // 清空按钮
    const clearBtn = document.getElementById('clear-btn');
    clearBtn.addEventListener('click', () => {
        if (confirm('确定要清空所有历史记录吗？')) {
            wsManager.clearHistory();
        }
    });
    
    // 过滤选择器
    const filterSelect = document.getElementById('filter-type');
    filterSelect.addEventListener('change', (e) => {
        wsManager.setFilter(e.target.value);
    });
    
    // 自动滚动开关
    const autoScrollCheckbox = document.getElementById('auto-scroll');
    autoScrollCheckbox.addEventListener('change', (e) => {
        wsManager.autoScroll = e.target.checked;
    });
    
    // 模态弹窗关闭按钮
    const modalClose = document.getElementById('modal-close');
    modalClose.addEventListener('click', () => {
        wsManager.closeModal();
    });
    
    // 点击模态弹窗背景关闭
    const modal = document.getElementById('packet-modal');
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            wsManager.closeModal();
        }
    });
    
    // ESC键关闭模态弹窗
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            wsManager.closeModal();
        }
    });
}

/**
 * 初始化时间显示
 */
function initializeTimeDisplay() {
    const timeElement = document.getElementById('current-time');
    
    function updateTime() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
        timeElement.textContent = timeStr;
    }
    
    // 立即更新一次
    updateTime();
    
    // 每秒更新
    setInterval(updateTime, 1000);
}

/**
 * 工具函数：复制文本到剪贴板
 */
function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('已复制到剪贴板', 'success');
        }).catch(err => {
            console.error('复制失败:', err);
            fallbackCopyToClipboard(text);
        });
    } else {
        fallbackCopyToClipboard(text);
    }
}

/**
 * 备用复制方法
 */
function fallbackCopyToClipboard(text) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    document.body.appendChild(textArea);
    textArea.select();
    
    try {
        document.execCommand('copy');
        showToast('已复制到剪贴板', 'success');
    } catch (err) {
        console.error('复制失败:', err);
        showToast('复制失败', 'error');
    }
    
    document.body.removeChild(textArea);
}

/**
 * 显示Toast通知
 */
function showToast(message, type = 'info') {
    // 创建toast元素
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    // 添加样式
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#00FF7F' : type === 'error' ? '#FF4444' : '#00BFFF'};
        color: #000;
        padding: 15px 25px;
        border: 4px solid #000;
        border-radius: 12px;
        font-weight: 700;
        box-shadow: 5px 5px 0 #000;
        z-index: 10000;
        animation: slideInRight 0.3s ease-out;
    `;
    
    document.body.appendChild(toast);
    
    // 3秒后移除
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease-in';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

/**
 * 格式化字节大小
 */
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

/**
 * 格式化时间戳
 */
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
}

/**
 * 下载数据为JSON文件
 */
function downloadAsJSON(data, filename) {
    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showToast('文件已下载', 'success');
}

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 导出工具函数供全局使用
window.copyToClipboard = copyToClipboard;
window.formatBytes = formatBytes;
window.formatTimestamp = formatTimestamp;
window.downloadAsJSON = downloadAsJSON;
window.showToast = showToast;

console.log('✅ 主JavaScript模块加载完成');
