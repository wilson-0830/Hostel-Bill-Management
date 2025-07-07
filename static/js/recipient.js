// PIN码设置
document.getElementById('pin-form').addEventListener('submit', function(e) {
    e.preventDefault();
    const digits = Array.from(document.querySelectorAll('.pin-digit'));
    const pin = digits.map(d => d.value).join('');
    
    if(pin.length !== 4) {
        alert('请输入4位PIN码');
        return;
    }
    
    fetch('/api/recipient/set-pin', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ pin })
    })
    .then(response => {
        if(response.ok) {
            document.getElementById('pin-setup').style.display = 'none';
            document.getElementById('main-workspace').style.display = 'block';
        }
    });
});

// 标签页切换
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        const tabId = this.dataset.tab;
        
        // 更新活动标签
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        
        // 显示对应内容
        document.querySelectorAll('.tab-content').forEach(content => {
            content.style.display = 'none';
        });
        document.getElementById(`${tabId}-tab`).style.display = 'block';
    });
});

// 创建收款项目
document.getElementById('create-item-btn').addEventListener('click', function() {
    // 显示创建表单或弹窗
    // 实现创建逻辑
});

<!-- templates/recipient_studio.html -->
{% extends "base.html" %}

{% block title %}支付平台 - 收款工作室{% endblock %}

{% block extra_css %}
<style>
    /* Studio-specific styles here */
</style>
{% endblock %}

{% block content %}
<div class="studio-container">
    <!-- Main workspace content here -->
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/recipient.js') }}"></script>
{% endblock %}