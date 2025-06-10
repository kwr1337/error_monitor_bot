<?php

class ErrorMonitor {
    private $projectToken;
    private $apiUrl;
    private $batchSize;
    private $flushInterval;
    private $errorQueue = [];
    private $lastFlush;
    
    public function __construct($options = []) {
        $this->projectToken = $options['projectToken'] ?? null;
        if (!$this->projectToken) {
            throw new \Exception('Project token is required');
        }
        
        $this->apiUrl = $options['apiUrl'] ?? 'http://localhost:8000/api/v1';
        $this->batchSize = $options['batchSize'] ?? 10;
        $this->flushInterval = $options['flushInterval'] ?? 60; // 60 seconds
        $this->lastFlush = time();
        
        // Register shutdown function to flush remaining errors
        register_shutdown_function([$this, 'flush']);
        
        // Set error handler
        set_error_handler([$this, 'handleError']);
        
        // Set exception handler
        set_exception_handler([$this, 'handleException']);
    }
    
    public function handleError($errno, $errstr, $errfile, $errline) {
        $error = new \ErrorException($errstr, 0, $errno, $errfile, $errline);
        $this->logError($error);
        
        // Don't execute PHP's internal error handler
        return true;
    }
    
    public function handleException($exception) {
        $this->logError($exception);
    }
    
    public function logError($error, $severity = 'error', $context = []) {
        try {
            $errorData = [
                'project_token' => $this->projectToken,
                'error' => [
                    'type' => get_class($error),
                    'message' => $error->getMessage(),
                    'stack_trace' => $error->getTraceAsString(),
                    'severity' => $severity,
                    'timestamp' => date('c'),
                    'context' => array_merge($context, [
                        'file' => $error->getFile(),
                        'line' => $error->getLine(),
                        'php_version' => PHP_VERSION,
                        'server' => $_SERVER ?? []
                    ])
                ]
            ];
            
            $this->errorQueue[] = $errorData;
            
            if (count($this->errorQueue) >= $this->batchSize) {
                $this->flush();
            }
        } catch (\Exception $e) {
            error_log('Failed to log error: ' . $e->getMessage());
        }
    }
    
    public function flush() {
        if (empty($this->errorQueue)) {
            return;
        }
        
        if (time() - $this->lastFlush < $this->flushInterval) {
            return;
        }
        
        $errors = array_splice($this->errorQueue, 0, $this->batchSize);
        
        try {
            $ch = curl_init($this->apiUrl . '/log');
            
            curl_setopt_array($ch, [
                CURLOPT_POST => true,
                CURLOPT_POSTFIELDS => json_encode(['errors' => $errors]),
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_HTTPHEADER => [
                    'Content-Type: application/json'
                ],
                CURLOPT_TIMEOUT => 5
            ]);
            
            $response = curl_exec($ch);
            $statusCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
            
            if ($statusCode !== 200) {
                throw new \Exception("API returned $statusCode: $response");
            }
            
            $this->lastFlush = time();
            
        } catch (\Exception $e) {
            error_log('Failed to flush errors: ' . $e->getMessage());
            // Return errors to queue
            array_unshift($this->errorQueue, ...$errors);
        } finally {
            if (isset($ch)) {
                curl_close($ch);
            }
        }
    }
}

// Example usage:
/*
$monitor = new ErrorMonitor([
    'projectToken' => 'your-project-token'
]);

try {
    // Some code that might throw
    throw new Exception('Test error');
} catch (Exception $e) {
    $monitor->logError($e);
}
*/ 