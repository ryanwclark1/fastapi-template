/**
 * k6 Load Testing Scenarios
 *
 * This file defines load test scenarios for the FastAPI application.
 *
 * Usage:
 *   # Run with default scenario
 *   k6 run tests/load_tests/k6/scenarios.js
 *
 *   # Run with specific scenario
 *   k6 run --env SCENARIO=spike tests/load_tests/k6/scenarios.js
 *
 *   # Run with custom parameters
 *   k6 run --vus 50 --duration 5m tests/load_tests/k6/scenarios.js
 *
 *   # Output to JSON for analysis
 *   k6 run --out json=results.json tests/load_tests/k6/scenarios.js
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const reminderListDuration = new Trend('reminder_list_duration');
const reminderCreateDuration = new Trend('reminder_create_duration');
const searchDuration = new Trend('search_duration');

// Configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

// Scenario definitions
export const options = {
    scenarios: {
        // Constant load scenario
        constant_load: {
            executor: 'constant-vus',
            vus: 10,
            duration: '2m',
            gracefulStop: '30s',
        },

        // Ramping load scenario (default)
        ramping_load: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: 20 },  // Ramp up
                { duration: '1m', target: 20 },   // Stay at 20
                { duration: '30s', target: 50 },  // Ramp to 50
                { duration: '1m', target: 50 },   // Stay at 50
                { duration: '30s', target: 0 },   // Ramp down
            ],
            gracefulRampDown: '30s',
        },

        // Spike test scenario
        spike_test: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '10s', target: 100 }, // Sudden spike
                { duration: '1m', target: 100 },  // Hold spike
                { duration: '10s', target: 0 },   // Quick drop
            ],
            startTime: '0s',
        },

        // Stress test scenario
        stress_test: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '2m', target: 50 },
                { duration: '5m', target: 50 },
                { duration: '2m', target: 100 },
                { duration: '5m', target: 100 },
                { duration: '2m', target: 150 },
                { duration: '5m', target: 150 },
                { duration: '5m', target: 0 },
            ],
        },

        // Soak test scenario (long duration)
        soak_test: {
            executor: 'constant-vus',
            vus: 30,
            duration: '30m',
        },
    },

    thresholds: {
        http_req_duration: ['p(95)<500', 'p(99)<1000'],
        http_req_failed: ['rate<0.01'],
        errors: ['rate<0.05'],
        reminder_list_duration: ['p(95)<300'],
        reminder_create_duration: ['p(95)<500'],
        search_duration: ['p(95)<400'],
    },
};

// Helper functions
function randomString(length) {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    for (let i = 0; i < length; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
}

function getHeaders() {
    return {
        'Content-Type': 'application/json',
        // Add auth header if needed:
        // 'Authorization': 'Bearer ' + __ENV.AUTH_TOKEN,
    };
}

// Test scenarios
export default function () {
    const headers = getHeaders();

    group('Health Checks', function () {
        const healthRes = http.get(`${BASE_URL}${API_PREFIX}/health`);
        check(healthRes, {
            'health check status is 200': (r) => r.status === 200,
        });

        const readyRes = http.get(`${BASE_URL}${API_PREFIX}/health/ready`);
        check(readyRes, {
            'readiness check status is 200': (r) => r.status === 200,
        });
    });

    group('Reminders API', function () {
        // List reminders
        const listStart = Date.now();
        const listRes = http.get(`${BASE_URL}${API_PREFIX}/reminders`, { headers });
        reminderListDuration.add(Date.now() - listStart);

        const listSuccess = check(listRes, {
            'list reminders status is 200 or 401': (r) => r.status === 200 || r.status === 401,
        });
        errorRate.add(!listSuccess);

        // Create reminder
        const createPayload = JSON.stringify({
            title: `k6 Test Reminder ${randomString(6)}`,
            description: 'Created by k6 load test',
            remind_at: new Date(Date.now() + 86400000).toISOString(),
        });

        const createStart = Date.now();
        const createRes = http.post(
            `${BASE_URL}${API_PREFIX}/reminders`,
            createPayload,
            { headers }
        );
        reminderCreateDuration.add(Date.now() - createStart);

        const createSuccess = check(createRes, {
            'create reminder status is 201 or 401': (r) => r.status === 201 || r.status === 401,
        });
        errorRate.add(!createSuccess);

        // If created, try to get it
        if (createRes.status === 201) {
            try {
                const created = JSON.parse(createRes.body);
                const getRes = http.get(
                    `${BASE_URL}${API_PREFIX}/reminders/${created.id}`,
                    { headers }
                );
                check(getRes, {
                    'get reminder status is 200': (r) => r.status === 200,
                });
            } catch (e) {
                // Ignore JSON parse errors
            }
        }
    });

    group('Search API', function () {
        const searchTerms = ['meeting', 'important', 'todo', 'call', 'review'];
        const query = searchTerms[Math.floor(Math.random() * searchTerms.length)];

        const searchStart = Date.now();
        const searchRes = http.get(
            `${BASE_URL}${API_PREFIX}/search?q=${query}`,
            { headers }
        );
        searchDuration.add(Date.now() - searchStart);

        check(searchRes, {
            'search status is 200 or 401': (r) => r.status === 200 || r.status === 401,
        });
    });

    group('Audit Logs', function () {
        const auditRes = http.get(
            `${BASE_URL}${API_PREFIX}/audit/logs?limit=10`,
            { headers }
        );
        check(auditRes, {
            'audit logs status is 200 or 401': (r) => r.status === 200 || r.status === 401,
        });
    });

    // Random sleep between iterations
    sleep(Math.random() * 2 + 1);
}

// Lifecycle hooks
export function setup() {
    console.log(`Starting load test against ${BASE_URL}`);

    // Verify service is up
    const res = http.get(`${BASE_URL}${API_PREFIX}/health`);
    if (res.status !== 200) {
        throw new Error(`Service not healthy: ${res.status}`);
    }

    return { startTime: Date.now() };
}

export function teardown(data) {
    const duration = (Date.now() - data.startTime) / 1000;
    console.log(`Load test completed in ${duration.toFixed(2)} seconds`);
}
