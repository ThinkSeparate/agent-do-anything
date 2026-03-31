// Game variables
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreElement = document.getElementById('score');
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');
const resetBtn = document.getElementById('resetBtn');

const gridSize = 20;
const tileCount = canvas.width / gridSize;

let snake = [
    {x: 10, y: 10}
];
let food = {};
let dx = 0;
let dy = 0;
let score = 0;
let gameRunning = false;
let gamePaused = false;
let gameLoop;

// Initialize food
function generateFood() {
    food = {
        x: Math.floor(Math.random() * tileCount),
        y: Math.floor(Math.random() * tileCount)
    };
    // Ensure food does not appear on the snake
    for (let segment of snake) {
        if (segment.x === food.x && segment.y === food.y) {
            generateFood();
            return;
        }
    }
}

// Draw game elements
function drawGame() {
    // Clear canvas
    ctx.fillStyle = 'black';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw snake
    ctx.fillStyle = 'lime';
    for (let segment of snake) {
        ctx.fillRect(segment.x * gridSize, segment.y * gridSize, gridSize - 2, gridSize - 2);
    }

    // Draw food
    ctx.fillStyle = 'red';
    ctx.fillRect(food.x * gridSize, food.y * gridSize, gridSize - 2, gridSize - 2);
}

// Update game state
function updateGame() {
    if (!gameRunning || gamePaused) return;

    // Move snake head
    const head = {x: snake[0].x + dx, y: snake[0].y + dy};
    snake.unshift(head);

    // Check for food collision
    if (head.x === food.x && head.y === food.y) {
        score += 10;
        scoreElement.textContent = score;
        generateFood();
    } else {
        snake.pop(); // Remove tail if no food eaten
    }

    // Check for collisions
    if (head.x < 0 || head.x >= tileCount || head.y < 0 || head.y >= tileCount) {
        gameOver();
        return;
    }
    for (let i = 1; i < snake.length; i++) {
        if (head.x === snake[i].x && head.y === snake[i].y) {
            gameOver();
            return;
        }
    }

    drawGame();
}

// Game loop function
function runGame() {
    updateGame();
    if (gameRunning && !gamePaused) {
        gameLoop = setTimeout(runGame, 100); // 10 frames per second
    }
}

// Game over function
function gameOver() {
    gameRunning = false;
    clearTimeout(gameLoop);
    alert('Game Over! Your score: ' + score);
}

// Start game function
function startGame() {
    if (gameRunning) return;
    // Reset snake and direction
    snake = [{x: 10, y: 10}];
    dx = 0;
    dy = 0;
    score = 0;
    scoreElement.textContent = score;
    generateFood();
    gameRunning = true;
    gamePaused = false;
    drawGame();
    runGame();
}

// Pause game function
function pauseGame() {
    if (!gameRunning) return;
    gamePaused = !gamePaused;
    if (gamePaused) {
        pauseBtn.textContent = 'Resume';
        clearTimeout(gameLoop);
    } else {
        pauseBtn.textContent = 'Pause';
        runGame();
    }
}

// Reset game function
function resetGame() {
    gameRunning = false;
    gamePaused = false;
    clearTimeout(gameLoop);
    snake = [{x: 10, y: 10}];
    dx = 0;
    dy = 0;
    score = 0;
    scoreElement.textContent = score;
    generateFood();
    drawGame();
    pauseBtn.textContent = 'Pause';
}

// Event listeners for keyboard controls
document.addEventListener('keydown', (e) => {
    if (!gameRunning || gamePaused) return;
    // Prevent snake from reversing into itself
    switch(e.key) {
        case 'ArrowUp':
            if (dy !== 1) { dx = 0; dy = -1; }
            break;
        case 'ArrowDown':
            if (dy !== -1) { dx = 0; dy = 1; }
            break;
        case 'ArrowLeft':
            if (dx !== 1) { dx = -1; dy = 0; }
            break;
        case 'ArrowRight':
            if (dx !== -1) { dx = 1; dy = 0; }
            break;
    }
});

// Button event listeners
startBtn.addEventListener('click', startGame);
pauseBtn.addEventListener('click', pauseGame);
resetBtn.addEventListener('click', resetGame);

// Initial draw
generateFood();
drawGame();