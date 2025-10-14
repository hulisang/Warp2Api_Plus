/**
 * 账号池管理JavaScript
 * 负责调用后端API进行账号池管理操作
 */

class PoolManager {
    constructor() {
        // API端点配置（通过server.py代理转发）
        this.poolApiBase = '/api/pool';
        
        // 数据缓存
        this.accounts = [];
        this.sessions = {};
        this.poolStatus = null;
        
        // 过滤和搜索
        this.currentFilter = 'all';
        this.searchQuery = '';
        
        // 定时刷新
        this.refreshInterval = null;
    }
    
    /**
     * 初始化
     */
    async init() {
        console.log('📋 初始化账号池管理器');
        
        // 绑定事件
        this.bindEvents();
        
        // 初始化时间显示
        this.updateTime();
        setInterval(() => this.updateTime(), 1000);
        
        // 加载数据
        await this.refreshAll();
        
        // 启动自动刷新（每30秒）
        this.refreshInterval = setInterval(() => this.refreshAll(), 30000);
    }
    
    /**
     * 绑定事件
     */
    bindEvents() {
        // 分配按钮
        document.getElementById('allocate-btn').addEventListener('click', () => {
            this.showAllocateModal();
        });
        
        // 添加账号按钮
        document.getElementById('add-account-btn').addEventListener('click', () => {
            this.showAddAccountModal();
        });
        
        // 刷新按钮
        document.getElementById('refresh-btn').addEventListener('click', () => {
            this.refreshAll();
        });
        
        // 搜索输入
        document.getElementById('search-input').addEventListener('input', (e) => {
            this.searchQuery = e.target.value.toLowerCase();
            this.filterAndRenderAccounts();
        });
        
        // 状态过滤标签
        document.querySelectorAll('#status-filter .tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // 更新激活状态
                document.querySelectorAll('#status-filter .tab-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                
                // 更新过滤器
                this.currentFilter = e.target.dataset.status;
                this.filterAndRenderAccounts();
            });
        });
        
        // 分配确认
        document.getElementById('confirm-allocate').addEventListener('click', () => {
            this.allocateAccounts();
        });
        
        // 模态弹窗关闭按钮
        document.getElementById('modal-close-allocate').addEventListener('click', () => {
            this.closeModal('allocate-modal');
        });
        
        document.getElementById('modal-close-account').addEventListener('click', () => {
            this.closeModal('account-modal');
        });
        
        document.getElementById('modal-close-add').addEventListener('click', () => {
            this.closeModal('add-account-modal');
        });
        
        // 添加账号确认
        document.getElementById('confirm-add-account').addEventListener('click', () => {
            this.addAccountFromLink();
        });
        
        // 下一步按钮
        document.getElementById('next-step-btn').addEventListener('click', () => {
            this.showStep2();
        });
        
        // 复制链接按钮
        document.getElementById('copy-signup-url').addEventListener('click', () => {
            this.copySignupUrl();
        });
        
        // ESC键关闭模态弹窗
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeModal('allocate-modal');
                this.closeModal('account-modal');
                this.closeModal('add-account-modal');
            }
        });
    }
    
    /**
     * 刷新所有数据
     */
    async refreshAll() {
        console.log('🔄 刷新账号池数据...');
        
        try {
            // 并行请求状态和账号列表
            await this.loadPoolStatus();
            await this.filterAndRenderAccounts();
            
            this.updatePoolStatus('已刷新', true);
        } catch (error) {
            console.error('刷新失败:', error);
            this.updatePoolStatus('刷新失败', false);
            this.showNotification('刷新失败: ' + error.message, 'error');
        }
    }
    
    /**
     * 加载账号池状态
     */
    async loadPoolStatus() {
        try {
            const response = await fetch(`${this.poolApiBase}/status`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            this.poolStatus = data;
            
            console.log('✅ 账号池状态:', data);
            
            // 更新统计显示
            this.updateStats(data);
            
            return data;
        } catch (error) {
            console.error('加载状态失败:', error);
            throw error;
        }
    }
    
    /**
     * 更新统计数据显示
     */
    updateStats(data) {
        // 匹配 pool_service.py 的get_pool_status()返回格式
        const totalAccounts = (data.total_active || 0) + (data.total_expired || 0);
        document.getElementById('total-accounts').textContent = totalAccounts;
        document.getElementById('active-accounts').textContent = data.total_active || 0;
        document.getElementById('blocked-accounts').textContent = data.total_expired || 0; // expired用作封禁数
        document.getElementById('active-sessions').textContent = data.active_sessions || 0;
    }
    
    /**
     * 分配账号
     */
    async allocateAccounts() {
        const count = parseInt(document.getElementById('allocate-count').value);
        const duration = parseInt(document.getElementById('session-duration').value);
        
        if (count < 1 || count > 10) {
            this.showNotification('账号数量必须在1-10之间', 'error');
            return;
        }
        
        if (duration < 60) {
            this.showNotification('会话时长至少60秒', 'error');
            return;
        }
        
        try {
            const response = await fetch(`${this.poolApiBase}/accounts/allocate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    count: count,
                    session_duration: duration
                })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            console.log('✅ 账号分配成功:', data);
            this.showNotification(`成功分配 ${data.accounts.length} 个账号`, 'success');
            
            // 关闭模态弹窗
            this.closeModal('allocate-modal');
            
            // 刷新数据
            await this.refreshAll();
            
            // 显示分配结果
            this.showAllocationResult(data);
            
        } catch (error) {
            console.error('分配账号失败:', error);
            this.showNotification('分配失败: ' + error.message, 'error');
        }
    }
    
    /**
     * 释放会话
     */
    async releaseSession(sessionId) {
        if (!confirm(`确定要释放会话 ${sessionId.substring(0, 8)}... 吗？`)) {
            return;
        }
        
        try {
            const response = await fetch(`${this.poolApiBase}/accounts/release`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    session_id: sessionId
                })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            console.log('✅ 会话释放成功:', data);
            this.showNotification('会话已释放', 'success');
            
            // 刷新数据
            await this.refreshAll();
            
        } catch (error) {
            console.error('释放会话失败:', error);
            this.showNotification('释放失败: ' + error.message, 'error');
        }
    }
    
    /**
     * 标记账号为已封禁
     */
    async markAccountBlocked(email) {
        if (!confirm(`确定要标记账号 ${email} 为已封禁吗？`)) {
            return;
        }
        
        try {
            const response = await fetch(`${this.poolApiBase}/accounts/mark_blocked`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email: email
                })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            console.log('✅ 账号标记成功:', data);
            this.showNotification('账号已标记为封禁', 'success');
            
            // 刷新数据
            await this.refreshAll();
            
        } catch (error) {
            console.error('标记账号失败:', error);
            this.showNotification('标记失败: ' + error.message, 'error');
        }
    }
    
    /**
     * 显示分配结果
     */
    showAllocationResult(data) {
        const { session_id, accounts, expires_at } = data;
        
        const container = document.getElementById('session-container');
        
        // 移除空状态
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }
        
        // 创建会话卡片
        const card = document.createElement('div');
        card.className = 'session-card';
        
        const expiresDate = new Date(expires_at * 1000);
        
        card.innerHTML = `
            <div class="session-header">
                <div class="session-id">${session_id.substring(0, 16)}...</div>
                <span class="status-tag">活动中</span>
            </div>
            <div class="session-info">
                <div class="info-item">
                    <div class="info-label">账号数量</div>
                    <div class="info-value">${accounts.length}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">过期时间</div>
                    <div class="info-value">${expiresDate.toLocaleString('zh-CN')}</div>
                </div>
            </div>
            <div class="action-buttons">
                <button class="action-btn danger" onclick="poolManager.releaseSession('${session_id}')">
                    释放会话
                </button>
            </div>
        `;
        
        container.insertBefore(card, container.firstChild);
    }
    
    /**
     * 加载账号列表
     */
    async loadAccounts(status = null, limit = 100, offset = 0) {
        try {
            let url = `${this.poolApiBase}/accounts/list?limit=${limit}&offset=${offset}`;
            if (status && status !== 'all') {
                url += `&status=${status}`;
            }
            
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            this.accounts = data.accounts || [];
            
            console.log('✅ 账号列表:', data);
            
            return data;
        } catch (error) {
            console.error('加载账号列表失败:', error);
            throw error;
        }
    }
    
    /**
     * 过滤并渲染账号列表
     */
    async filterAndRenderAccounts() {
        const container = document.getElementById('account-container');
        
        try {
            // 加载账号列表
            await this.loadAccounts(this.currentFilter);
            
            // 过滤搜索结果
            let filteredAccounts = this.accounts;
            if (this.searchQuery) {
                filteredAccounts = this.accounts.filter(account => 
                    account.email.toLowerCase().includes(this.searchQuery)
                );
            }
            
            // 清空容器
            container.innerHTML = '';
            
            if (filteredAccounts.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">🔍</div>
                        <div class="empty-text">没有符合条件的账号</div>
                    </div>
                `;
                return;
            }
            
            // 渲染账号卡片
            for (const account of filteredAccounts) {
                const card = this.createAccountCard(account);
                container.appendChild(card);
            }
            
        } catch (error) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">❌</div>
                    <div class="empty-text">加载失败: ${error.message}</div>
                </div>
            `;
        }
    }
    
    /**
     * 创建账号卡片
     */
    createAccountCard(account) {
        const card = document.createElement('div');
        card.className = 'account-card';
        
        // 状态标签
        let statusClass = '';
        let statusText = '';
        if (account.is_locked) {
            statusClass = 'locked';
            statusText = '已锁定';
        } else if (account.status === 'active') {
            statusClass = '';
            statusText = '活跃';
        } else if (account.status === 'blocked') {
            statusClass = 'blocked';
            statusText = '已封禁';
        }
        
        // 格式化时间
        const lastUsed = account.last_used ? 
            new Date(account.last_used).toLocaleString('zh-CN') : '未使用';
        const createdAt = new Date(account.created_at).toLocaleString('zh-CN');
        
        card.innerHTML = `
            <div class="account-header">
                <div class="account-email">${account.email}</div>
                <span class="status-tag ${statusClass}">${statusText}</span>
            </div>
            <div class="account-info">
                <div class="info-item">
                    <div class="info-label">最后使用</div>
                    <div class="info-value">${lastUsed}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">创建时间</div>
                    <div class="info-value">${createdAt}</div>
                </div>
                ${account.is_locked ? `
                    <div class="info-item">
                        <div class="info-label">锁定由</div>
                        <div class="info-value">${account.locked_by_session.substring(0, 8)}...</div>
                    </div>
                ` : ''}
            </div>
            <div class="action-buttons">
                ${account.status === 'active' && !account.is_locked ? `
                    <button class="action-btn danger" onclick="poolManager.markAccountBlocked('${account.email}')">
                        标记封禁
                    </button>
                ` : ''}
                <button class="action-btn" onclick="poolManager.showAccountDetail('${account.email}')">
                    查看详情
                </button>
            </div>
        `;
        
        return card;
    }
    
    /**
     * 显示账号详情
     */
    showAccountDetail(email) {
        const account = this.accounts.find(a => a.email === email);
        if (!account) return;
        
        const modal = document.getElementById('account-modal');
        const detailContainer = document.getElementById('account-detail');
        
        detailContainer.innerHTML = `
            <div class="info-item">
                <div class="info-label">邮箱</div>
                <div class="info-value">${account.email}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Local ID</div>
                <div class="info-value">${account.local_id || 'N/A'}</div>
            </div>
            <div class="info-item">
                <div class="info-label">状态</div>
                <div class="info-value">${account.status}</div>
            </div>
            <div class="info-item">
                <div class="info-label">是否锁定</div>
                <div class="info-value">${account.is_locked ? '是' : '否'}</div>
            </div>
            ${account.proxy_info ? `
                <div class="info-item">
                    <div class="info-label">代理信息</div>
                    <div class="info-value">${account.proxy_info}</div>
                </div>
            ` : ''}
            ${account.user_agent ? `
                <div class="info-item">
                    <div class="info-label">User Agent</div>
                    <div class="info-value">${account.user_agent}</div>
                </div>
            ` : ''}
        `;
        
        modal.classList.add('active');
    }
    
    /**
     * 显示分配模态弹窗
     */
    showAllocateModal() {
        document.getElementById('allocate-modal').classList.add('active');
    }
    
    /**
     * 显示添加账号模态弹窗
     */
    showAddAccountModal() {
        // 清空表单
        document.getElementById('add-email').value = '';
        document.getElementById('add-login-link').value = '';
        
        // 初始化为第一步：生成注册链接
        this.showStep1();
        
        document.getElementById('add-account-modal').classList.add('active');
    }
    
    /**
     * 显示第一步：生成注册链接
     */
    showStep1() {
        // 生成注册链接（UUID v4格式）
        const uuid = this.generateUUID();
        const signupUrl = `https://app.warp.dev/signup/remote?scheme=warp&state=${uuid}&public_beta=true`;
        
        // 显示步骤1，隐藏步骤2
        document.getElementById('step-1').style.display = 'block';
        document.getElementById('step-2').style.display = 'none';
        
        // 设置生成的链接
        document.getElementById('signup-url-display').textContent = signupUrl;
        
        // 更新按钮状态
        document.getElementById('next-step-btn').style.display = 'block';
        document.getElementById('confirm-add-account').style.display = 'none';
    }
    
    /**
     * 显示第二步：输入邮箱和登录链接
     */
    showStep2() {
        // 隐藏步骤1，显示步骤2
        document.getElementById('step-1').style.display = 'none';
        document.getElementById('step-2').style.display = 'block';
        
        // 更新按钮状态
        document.getElementById('next-step-btn').style.display = 'none';
        document.getElementById('confirm-add-account').style.display = 'block';
    }
    
    /**
     * 生成UUID v4
     */
    generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }
    
    /**
     * 复制注册链接到剪贴板
     */
    async copySignupUrl() {
        const urlText = document.getElementById('signup-url-display').textContent;
        
        try {
            await navigator.clipboard.writeText(urlText);
            this.showNotification('注册链接已复制到剪贴板', 'success');
        } catch (error) {
            console.error('复制失败:', error);
            this.showNotification('复制失败，请手动复制', 'error');
        }
    }
    
    /**
     * 从登录链接添加账号
     */
    async addAccountFromLink() {
        const email = document.getElementById('add-email').value.trim();
        const loginLink = document.getElementById('add-login-link').value.trim();
        
        // 验证输入
        if (!email) {
            this.showNotification('请输入邮箱地址', 'error');
            return;
        }
        
        if (!loginLink) {
            this.showNotification('请输入登录链接', 'error');
            return;
        }
        
        // 验证邮箱格式
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            this.showNotification('邮箱地址格式不正确', 'error');
            return;
        }
        
        // 验证是否包含oobCode
        if (!loginLink.includes('oobCode')) {
            this.showNotification('登录链接不包含 oobCode，请确认链接是否正确', 'error');
            return;
        }
        
        try {
            // 禁用按钮防止重复提交
            const confirmBtn = document.getElementById('confirm-add-account');
            confirmBtn.disabled = true;
            confirmBtn.querySelector('.btn-text').textContent = '添加中...';
            
            const response = await fetch(`${this.poolApiBase}/accounts/add_from_link`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email: email,
                    login_link: loginLink
                })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            console.log('✅ 账号添加成功:', data);
            this.showNotification(`账号 ${email} 已成功添加`, 'success');
            
            // 关闭模态弹窗
            this.closeModal('add-account-modal');
            
            // 刷新数据
            await this.refreshAll();
            
        } catch (error) {
            console.error('添加账号失败:', error);
            this.showNotification('添加失败: ' + error.message, 'error');
        } finally {
            // 恢复按钮状态
            const confirmBtn = document.getElementById('confirm-add-account');
            confirmBtn.disabled = false;
            confirmBtn.querySelector('.btn-text').textContent = '确认添加';
        }
    }
    
    /**
     * 关闭模态弹窗
     */
    closeModal(modalId) {
        document.getElementById(modalId).classList.remove('active');
    }
    
    /**
     * 更新池状态显示
     */
    updatePoolStatus(text, isHealthy) {
        const badge = document.getElementById('pool-status');
        const statusText = badge.querySelector('.status-text');
        
        statusText.textContent = text;
        
        if (isHealthy) {
            badge.classList.remove('disconnected');
            badge.classList.add('connected');
        } else {
            badge.classList.remove('connected');
            badge.classList.add('disconnected');
        }
    }
    
    /**
     * 更新时间显示
     */
    updateTime() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
        document.getElementById('current-time').textContent = timeStr;
    }
    
    /**
     * 显示通知
     */
    showNotification(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        
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
        
        setTimeout(() => {
            toast.style.animation = 'slideOutRight 0.3s ease-in';
            setTimeout(() => {
                document.body.removeChild(toast);
            }, 300);
        }, 3000);
    }
}

// 创建全局实例
const poolManager = new PoolManager();

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 账号池管理页面启动');
    poolManager.init();
});

console.log('✅ 账号池管理模块加载完成');
