/**
 * Local University Mock Portal for End-to-End DOM Automation Testing
 */
import http from 'http';

const PORT = 4321;
const SESSIONS = new Set();

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const cookies = req.headers.cookie || '';
  const isLoggedIn = cookies.includes('session_token=valid_student_session');

  // 1. Dashboard / Attendance Page
  if (url.pathname === '/dashboard' || url.pathname === '/attendance') {
    if (!isLoggedIn) {
      res.writeHead(302, { Location: '/login' });
      return res.end();
    }

    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end(`
      <!DOCTYPE html>
      <html>
      <head><title>Student Portal - Dashboard</title></head>
      <body>
        <div id="ctl00_lblUserName" class="user-profile">Welcome, Student (232530)</div>
        <div id="attendance-panel">
          <h2>Academic Attendance Record</h2>
          <div class="attendance-percentage" id="ctl00_MainContent_lblOverallAttendance">89.4%</div>
          <div class="attendance-gap" id="ctl00_MainContent_lblAttendanceGap">+4 lectures safe</div>
          <table border="1">
            <tr><th>Course</th><th>Held</th><th>Attended</th><th>%</th></tr>
            <tr><td>Database Systems</td><td>32</td><td>29</td><td>90.6%</td></tr>
            <tr><td>Operating Systems</td><td>30</td><td>26</td><td>86.7%</td></tr>
          </table>
          <a href="/logout">Logout</a>
        </div>
      </body>
      </html>
    `);
  }

  // 2. Login Page
  if (url.pathname === '/login' || url.pathname === '/') {
    if (req.method === 'POST') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        // Authenticate student
        res.writeHead(302, {
          'Set-Cookie': 'session_token=valid_student_session; Path=/; HttpOnly',
          'Location': '/dashboard'
        });
        return res.end();
      });
      return;
    }

    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end(`
      <!DOCTYPE html>
      <html>
      <head><title>Student Portal - Login</title></head>
      <body>
        <form method="POST" action="/login">
          <h2>University Student Login</h2>
          <input name="txtRegNo" type="text" placeholder="Reg Number" value="232530" />
          <input name="txtPassword" type="password" placeholder="Password" value="demo123" />
          <input id="btnLogin" type="submit" value="Sign In" />
        </form>
      </body>
      </html>
    `);
  }

  // 3. Logout
  if (url.pathname === '/logout') {
    res.writeHead(302, {
      'Set-Cookie': 'session_token=; Path=/; Max-Age=0',
      'Location': '/login'
    });
    return res.end();
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`Mock University Portal running at http://localhost:${PORT}`);
});
