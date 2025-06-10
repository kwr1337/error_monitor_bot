class ErrorMonitor {
    constructor(options) {
        this.projectToken = options.projectToken;
        this.apiUrl = options.apiUrl || 'http://localhost:8000/api/v1';
        this.batchSize = options.batchSize || 10;
        this.flushInterval = options.flushInterval || 60000; // 60 seconds
        
        this.errorQueue = [];
        this.lastFlush = Date.now();
        
        // Start background worker
        this.startWorker();
        
        // Automatically catch unhandled errors and rejections
        if (typeof window !== 'undefined') {
            // Browser environment
            window.onerror = (msg, url, line, col, error) => {
                this.logError(error || new Error(msg));
            };
            
            window.addEventListener('unhandledrejection', (event) => {
                this.logError(event.reason);
            });
        } else if (typeof process !== 'undefined') {
            // Node.js environment
            process.on('uncaughtException', (error) => {
                this.logError(error);
            });
            
            process.on('unhandledRejection', (reason) => {
                this.logError(reason);
            });
        }
    }
    
    startWorker() {
        setInterval(() => {
            if (Date.now() - this.lastFlush >= this.flushInterval) {
                this.flush();
            }
        }, 1000);
    }
    
    async logError(error, severity = 'error', context = {}) {
        try {
            const errorData = {
                project_token: this.projectToken,
                error: {
                    type: error.name,
                    message: error.message,
                    stack_trace: error.stack,
                    severity: severity,
                    timestamp: new Date().toISOString(),
                    context: {
                        ...context,
                        userAgent: typeof window !== 'undefined' ? window.navigator.userAgent : 'Node.js',
                        platform: typeof window !== 'undefined' ? 'browser' : 'node'
                    }
                }
            };
            
            this.errorQueue.push(errorData);
            
            if (this.errorQueue.length >= this.batchSize) {
                await this.flush();
            }
        } catch (e) {
            console.error('Failed to log error:', e);
        }
    }
    
    async flush() {
        if (this.errorQueue.length === 0) return;
        
        const errors = this.errorQueue.splice(0, this.batchSize);
        
        try {
            const response = await fetch(`${this.apiUrl}/log`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ errors })
            });
            
            if (!response.ok) {
                throw new Error(`API returned ${response.status}: ${await response.text()}`);
            }
            
            this.lastFlush = Date.now();
        } catch (e) {
            console.error('Failed to flush errors:', e);
            // Return errors to queue
            this.errorQueue.unshift(...errors);
        }
    }
}

// Example usage in browser:
/*
const monitor = new ErrorMonitor({
    projectToken: 'your-project-token'
});

try {
    // Some code that might throw
    throw new Error('Test error');
} catch (error) {
    monitor.logError(error);
}
*/

// Example usage in Node.js:
if (typeof module !== 'undefined') {
    module.exports = ErrorMonitor;
} 