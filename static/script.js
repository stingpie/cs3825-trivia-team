/* ================================================================
       GLOBAL STATE
       This app has no framework (no React/Vue) - all state lives in
       plain JS variables here, and functions manually read/write the
       DOM to reflect that state. Keep this in mind: if two functions
       forget to update the same variable, the UI can get out of sync.
       ================================================================ */

    let activeAvatar = { icon: '👾', name: 'Neon Invader' };   // currently selected player avatar
    let currentScore = 0;                                      // score for the CURRENT game (solo or multiplayer)
    let currentStreak = 0;                                      // current correct-answer streak
    let currentQuestionIndex = 0;                                // index into whichever question list is active
    let showFullpageAnswers = false;                             // toggles answer-key visibility on the quiz detail page
    let soloCorrectAnswers = 0;                                  // running count of correct answers in solo mode (for accuracy %)
    let soloTotalAttempted = 0;                                  // running count of questions attempted in solo mode
    let hostTimerInterval = null;                                // setInterval handle for the host's countdown timer
    let selectedPacing = 'self';                                 // 'self' or 'host' - chosen on the Host Setup page
    let localCurrentQuestion = null;                             // the question object currently shown in multiplayer mode

    // server.py's lobby API (POST /api/rooms) generates the 4-digit PIN
    // server-side and returns it. activeRoomPin starts at '4821' purely as
    // a placeholder for the fully-offline/no-backend demo fallback in
    // handleJoinGame().
    let activeRoomPin = '4821';
    let activeRoomCode = null;      // the real room_code once a live room exists (host or joined)
    let isRoomHost = false;         // true if THIS session created the room (controls Start/End buttons)
    let roomPollInterval = null;    // setInterval handle for polling GET /api/rooms/<code> on the host screen

    // Logged-in user info (null = playing as a guest). Set by setLoggedInUser(),
    // cleared by handleLogout().
    let currentUser = null;
    let userStats = {
      gamesPlayed: 0,
      totalPoints: 0,
      bestStreak: 0,
      accuracy: 100,
      history: []
    };

    // Tracks which quiz is currently being played/hosted, so Solo, Host,
    // and multiplayer all pull questions for the right quiz.
    let activeQuizTitle = 'Networking Protocols';

    // Maps a local quiz title to the trivia_set_idx the backend assigned
    // when it was uploaded via POST /api/trivia (create_trivia). The
    // built-in demo quizzes have no backend record until a teacher saves
    // them through "Build New Quiz", so hosting a live room for one of
    // them will fail with "trivia set not found" (404) until that happens
    // at least once per quiz per server run. See apiPostQuiz() /
    // handleSaveBuilderQuiz(), which fill this in when a save succeeds.
    let quizBackendIndex = {};

    // Correct/attempted counters for multiplayer mode, used to compute
    // real accuracy when the game finishes.
    let mpCorrectAnswers = 0;
    let mpTotalAttempted = 0;

    // Which question number is currently live in a host-paced session,
    // shown on the host-paced scoreboard control.
    let hostQuestionIndex = 0;

    // The pacing mode of the room a STUDENT is currently playing in (as
    // returned by the join-room response), separate from `selectedPacing`
    // above, which is the host's choice on the Host Setup screen. In
    // "host" mode, the player doesn't advance their own question - they
    // poll for whatever the host has dispatched (see
    // startStudentQuestionPolling()).
    let joinedRoomPacingMode = 'self';
    let studentQuestionPollInterval = null;
    let lastSeenQuestionText = null;

    // Heartbeat ping loop (protocol_spec.json "HEARTBEAT", every 5s while
    // a login session is active) so reliability.py can tell live players
    // apart from disconnected ones.
    let heartbeatInterval = null;

    // security.py's require_valid_signature decorator checks an
    // X-Signature header against an HMAC-SHA256 of the raw request body,
    // using a server-side secret (TRIVIA_HMAC_SECRET env var). The browser
    // computes the same signature to talk to /api/trivia (POST) and
    // /api/trivia/verify, so this value must be set to whatever the team
    // is actually using to start server.py / trivia-manager.py.
    // A secret embedded in client-side JS is visible to anyone who views
    // source, so this only guards against accidental/incidental tampering,
    // not a malicious client.
    const HMAC_SHARED_SECRET = "2ab4343e8f40f233d2eefeb011056eb5";

    /* Hardcoded fallback quiz content, used whenever the backend
       (server.py / trivia-manager.py) isn't reachable or hasn't been
       wired up yet. See apiFetchTriviaQuestion() for how this is used
       as a fallback. */
    const quizDatabase = {
      "Networking Protocols": {
        tag: "Computer Science",
        questions: [
          { q: "Which default network transport port is standard for unencrypted HTTP traffic?", type: "Short Answer", answers: ["80", "port 80"], choices: [] },
          { q: "Which transport protocol guarantees ordered delivery and reliability?", type: "Multiple Choice", answers: ["TCP"], choices: ["TCP", "UDP", "ICMP", "IP"] },
          { q: "Which of the following are valid application layer protocols?", type: "Multiple Select", answers: ["HTTP", "DNS"], choices: ["HTTP", "DNS", "Ethernet", "IPsec"] }
        ]
      },
      "World History Essentials": {
        tag: "General Knowledge",
        questions: [
          { q: "In which year did World War II conclude?", type: "Short Answer", answers: ["1945"], choices: [] },
          { q: "The Magna Carta was signed in 1215.", type: "True / False", answers: ["True"], choices: ["True", "False"] }
        ]
      },
      "Web Security & Cryptography": {
        tag: "Cybersecurity",
        questions: [
          { q: "Which cryptographic protocol succeeded SSL for securing web traffic (HTTPS)?", type: "Short Answer", answers: ["TLS", "Transport Layer Security"], choices: [] },
          { q: "A Message Authentication Code (MAC) primarily provides which security guarantee?", type: "Multiple Choice", answers: ["Integrity"], choices: ["Integrity", "Confidentiality", "Availability", "Anonymity"] }
        ]
      }
    };

    /**
     * Normalizes a string for lenient answer comparison:
     * lowercases it, trims whitespace, and strips punctuation.
     * Used so "Port 80!" and "port 80" are treated as equal.
     */
    function normalizeString(str) { return str.toLowerCase().trim().replace(/[^\w\s]/gi, ''); }

    /**
     * Grades a player's typed answer against a question, mirroring the
     * grading rule in trivia-manager.py's TriviaSet.verify_answer():
     *   - "Multiple Select" questions require the submitted set of answers
     *     to exactly match the correct set (not just contain one of them).
     *   - every other type only needs the submitted answer to match ONE
     *     accepted answer.
     * `rawInput` is whatever the player typed - for Multiple Select,
     * players comma-separate their picks (see the placeholder text on the
     * answer inputs) and this splits on commas.
     * Returns { isCorrect, answerArray } so callers can both grade locally
     * and send the same properly-shaped array to apiVerifyAnswer().
     */
    function checkAnswerAgainstQuestion(question, rawInput) {
      const items = rawInput.split(',').map(s => s.trim()).filter(Boolean);
      const answerArray = items.length > 0 ? items : [rawInput];

      if (question.type === 'Multiple Select') {
        const correctSet = new Set(question.answers.map(normalizeString));
        const givenSet = new Set(answerArray.map(normalizeString));
        if (correctSet.size !== givenSet.size) return { isCorrect: false, answerArray };
        for (const item of correctSet) {
          if (!givenSet.has(item)) return { isCorrect: false, answerArray };
        }
        return { isCorrect: true, answerArray };
      }

      const isCorrect = question.answers.some(a => normalizeString(a) === normalizeString(rawInput));
      return { isCorrect, answerArray: [rawInput] };
    }

    /**
     * Computes the hex HMAC-SHA256 signature security.py's
     * require_valid_signature() expects in the X-Signature header, using
     * the Web Crypto API (crypto.subtle). Must be called with the exact
     * same string that gets sent as the request body - sign first, then
     * send that identical string, or the signatures won't match.
     */
    async function signRequestBody(bodyString) {
      const encoder = new TextEncoder();
      const key = await crypto.subtle.importKey(
        'raw',
        encoder.encode(HMAC_SHARED_SECRET),
        { name: 'HMAC', hash: 'SHA-256' },
        false,
        ['sign']
      );
      const signatureBuffer = await crypto.subtle.sign('HMAC', key, encoder.encode(bodyString));
      return Array.from(new Uint8Array(signatureBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * Shows a temporary bottom-right toast notification.
     * Auto-removes itself after 4 seconds, or can be dismissed early
     * by clicking the ✕.
     */
    function showCustomToast(message) {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      toast.className = 'toast-popup';
      toast.innerHTML = `<span>⚡ ${message}</span><span style="cursor:pointer;" onclick="this.parentElement.remove()">✕</span>`;
      container.appendChild(toast);
      setTimeout(() => toast.remove(), 4000);
    }

    // Generic modal open/close helpers - just toggle the .active class
    // which the CSS uses to flip display:none <-> display:flex.
    function openModal(id) { document.getElementById(id).classList.add('active'); }
    function closeModal(id) { document.getElementById(id).classList.remove('active'); }

    /**
     * Filters the home page's quiz cards to only show ones whose title or
     * category tag matches the typed text (case/punctuation-insensitive,
     * via normalizeString). An empty search shows every card again.
     */
    function filterQuizzes() {
      const query = normalizeString(document.getElementById('quiz-search-input').value);
      document.querySelectorAll('#home-view .quiz-card').forEach(card => {
        const title = card.querySelector('h3')?.innerText || '';
        const tag = card.querySelector('.quiz-tag')?.innerText || '';
        const haystack = normalizeString(`${title} ${tag}`);
        card.style.display = (!query || haystack.includes(query)) ? '' : 'none';
      });
    }

    /* ================================================================
       FLASK BACKEND INTEGRATION HELPERS
       Every one of these follows the same pattern:
         1. try to call the real backend endpoint
         2. if it works, use the real response
         3. if it throws (server down / network error / non-2xx not
            explicitly handled), fall back to local-only behavior
       This lets the front-end be developed and demoed even before
       server.py is finished or running.
       ================================================================ */

    /** Registers a new account. Every response branch (created, username
     * taken, other error, network failure) returns an explicit result. */
    async function apiRegisterUser(username, password, role = 'student') {
      try {
        const response = await fetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password, role })
        });
        if (response.status === 201) {
          showCustomToast("Account created successfully!");
          return { success: true, username, role };
        } else if (response.status === 409) {
          showCustomToast("Username is already taken!");
          return { success: false };
        } else {
          showCustomToast(`Registration failed (server said: ${response.status}).`);
          return { success: false };
        }
      } catch(e) {
        // Backend unreachable - just pretend it worked so the demo/dev flow
        // can continue locally.
        showCustomToast("Server offline, running in local session mode");
        return { success: true, username, role };
      }
    }

    async function apiLoginUser(username, password) {
      try {
        const response = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        if (response.ok) {
          const res = await response.json();
          showCustomToast("Logged in successfully!");
          return { success: true, username, role: res.role };
        } else {
          showCustomToast("Invalid login credentials!");
          return { success: false };
        }
      } catch(e) {
        // Backend unreachable: fall back to whatever role was last saved
        // locally for this username (defaults to 'teacher' if never saved).
        const savedRole = localStorage.getItem(`user_role_${username}`) || 'teacher';
        return { success: true, username, role: savedRole };
      }
    }

    /**
     * Saves a quiz to the backend. create_trivia (POST /api/trivia) is
     * guarded by both @require_role("teacher") and @require_valid_signature
     * in server.py, so this sends the X-Signature header (see
     * signRequestBody). The signature is computed over the exact same
     * string that's sent as the body, so `bodyString` is built once and
     * reused for both signing and the fetch call.
     */
    async function apiPostQuiz(quizPayload) {
      try {
        const bodyString = JSON.stringify(quizPayload);
        const signature = await signRequestBody(bodyString);
        const response = await fetch('/api/trivia', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Signature': signature },
          body: bodyString
        });
        if (response.ok) {
          const quizIdx = await response.text();
          showCustomToast(`Quiz saved to server! Quiz Set ID: ${quizIdx}`);
          return quizIdx;
        } else if (response.status === 401 || response.status === 403) {
          showCustomToast("⚠️ Saving to the server requires a Teacher account - kept locally only.");
        } else if (response.status === 400) {
          showCustomToast("⚠️ Server rejected the quiz signature/payload - kept locally only.");
        }
      } catch(e) {
        showCustomToast("Quiz saved locally!");
      }
      return null;
    }

    /**
     * Fetches the current question from the backend. Returns the question
     * object on success, `{ serverSignaledDone: true }` if the backend
     * was reached but has no next question to give (session ran past the
     * end of the trivia set), or `null` if the backend couldn't be
     * reached at all (network failure), which is the signal callers use
     * to fall back to local quiz data.
     */
    async function apiFetchTriviaQuestion() {
      try {
        const response = await fetch('/api/trivia');
        if (response.ok) {
          return await response.json();
        }
        return { serverSignaledDone: true };
      } catch(e) {
        console.log("Using fallback question logic");
      }
      return null;
    }

    /**
     * Sends the player's answer to the server for grading, signed with
     * X-Signature. server.py declares SUBMIT_ANSWER as
     * `@app.route("/api/trivia/verify", methods=["GET"])` and reads the
     * answer from a JSON body (`request.get_json()['answer']`), but
     * browsers cannot send a body on a GET/HEAD request - fetch() throws
     * a TypeError before any network call is made. This sends POST
     * instead, which will succeed once the backend route accepts POST too
     * (currently it only declares GET, so this call gets a 405 against the
     * real server, and the caller falls back to grading locally via
     * checkAnswerAgainstQuestion()).
     */
    async function apiVerifyAnswer(answerArr) {
      try {
        const payloadArray = Array.isArray(answerArr) ? answerArr : [answerArr];
        const bodyString = JSON.stringify({ answer: payloadArray });
        const signature = await signRequestBody(bodyString);
        const response = await fetch('/api/trivia/verify', {
          method: 'POST', // see note above - backend currently only declares GET
          headers: { 'Content-Type': 'application/json', 'X-Signature': signature },
          body: bodyString
        });
        if (response.ok) {
          const res = await response.json();
          return res.correct;
        }
      } catch(e) {
        console.log("Verifying locally");
      }
      return null;
    }

    async function apiNextQuestion() {
      try {
        const response = await fetch('/api/trivia/next');
        if (response.ok) {
          return await response.json();
        }
      } catch(e) {
        console.log("Advancing question locally");
      }
      return null;
    }

    /**
     * Downloads a Canvas-gradebook-style CSV of per-question correct/incorrect
     * counts for the currently active quiz (quizBackendIndex[activeQuizTitle]).
     * Tries the real analytics endpoint first; if that fails for any reason
     * (network error OR a non-ok response, which is also caught here) it
     * downloads a small hardcoded sample CSV instead so the "Export" button
     * always produces something during development/demos.
     * Same GET-with-body browser limitation as apiVerifyAnswer() - server.py
     * declares this route as GET but reads a JSON body, which browsers
     * can't send on a GET request, so this sends POST instead.
     */
    async function exportStudentGrades() {
      const idxOfTriviaSet = quizBackendIndex[activeQuizTitle] ?? 0;
      try {
        const response = await fetch('/api/trivia/analytics', {
          method: 'POST', // see note above - backend currently only declares GET
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ idx_of_trivia_set: idxOfTriviaSet })
        });

        if (response.ok) {
          const analyticsData = await response.json();
          
          let csvContent = "data:text/csv;charset=utf-8,Question Index,Correct Count,Incorrect Count\n";
          
          analyticsData.forEach((q, index) => {
            csvContent += `"${index + 1}","${q.correct}","${q.incorrect}"\n`;
          });

          const encodedUri = encodeURI(csvContent);
          const downloadAnchor = document.createElement('a');
          downloadAnchor.setAttribute("href", encodedUri);
          downloadAnchor.setAttribute("download", "canvas_gradebook_export.csv");
          document.body.appendChild(downloadAnchor);
          downloadAnchor.click();
          downloadAnchor.remove();

          showCustomToast("📋 Canvas-Ready CSV Grades Downloaded!");
        } else {
          showCustomToast("⚠️ No analytics found for this quiz set yet.");
        }
      } catch (e) {
        // Backend unreachable - download a small dummy CSV instead, purely
        // so the button has visible behavior during local development.
        let csvContent = "data:text/csv;charset=utf-8,Question Index,Correct Count,Incorrect Count\n1,5,0\n2,4,1\n";
        const encodedUri = encodeURI(csvContent);
        const downloadAnchor = document.createElement('a');
        downloadAnchor.setAttribute("href", encodedUri);
        downloadAnchor.setAttribute("download", "canvas_gradebook_export.csv");
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();

        showCustomToast("📋 Local CSV Grades Report Downloaded!");
      }
    }


    /* ================================================================
       UI & AUTH STATE MANAGEMENT
       ================================================================ */

    /**
     * Shared submit handler for BOTH the Login form and the Sign-Up form.
     * Figures out which one the user is on by checking which .view
     * currently has the .active class, then calls the matching API
     * helper and updates global auth state on success.
     */
    async function handleAuthSubmit(event) {
      event.preventDefault();
      const isSignUp = document.getElementById('signup-view').classList.contains('active');
      
      let res;
      if (isSignUp) {
        const u = document.getElementById('signup-email').value;
        const p = document.getElementById('signup-pass').value;
        const r = document.getElementById('signup-role')?.value || 'student';
        res = await apiRegisterUser(u, p, r);
      } else {
        const u = document.getElementById('user').value;
        const p = document.getElementById('pass').value;
        res = await apiLoginUser(u, p);
      }

      if (res && res.success) {
        setLoggedInUser(res.username, res.role || 'student');
        switchView('dashboard-view');
      }
    }

    /**
     * Marks the given username/role as the active session and updates
     * every UI element that depends on login state: header badge,
     * dashboard guest-warning banner, and the teacher-only panel. Role is
     * trusted from whatever the server/local-fallback said, and cached in
     * localStorage keyed by username as a convenience for the offline
     * fallback path.
     */
    function setLoggedInUser(username, role) {
      currentUser = { username, role };
      localStorage.setItem(`user_role_${username}`, role);

      document.getElementById('login-nav-btn').style.display = 'none';
      document.getElementById('user-profile-badge').style.display = 'flex';
      document.getElementById('nav-user-name').innerText = username;
      document.getElementById('nav-user-icon').innerText = role === 'teacher' ? '🎓' : '👤';

      document.getElementById('dash-guest-warning').style.display = 'none';
      document.getElementById('dash-role-badge').innerText = `${role.toUpperCase()} ACCOUNT`;
      document.getElementById('dash-subtitle-text').innerText = `Welcome back, ${username}! Syncing performance records.`;

      if (role === 'teacher') {
        document.getElementById('dash-teacher-panel').style.display = 'block';
      } else {
        document.getElementById('dash-teacher-panel').style.display = 'none';
      }

      updateDashboardStats();
    }

    /** Clears the active session and resets the dashboard back to "guest" view. */
    function handleLogout() {
      currentUser = null;
      document.getElementById('login-nav-btn').style.display = 'block';
      document.getElementById('user-profile-badge').style.display = 'none';

      document.getElementById('dash-guest-warning').style.display = 'flex';
      document.getElementById('dash-role-badge').innerText = 'GUEST SESSION';
      document.getElementById('dash-teacher-panel').style.display = 'none';
      document.getElementById('dash-subtitle-text').innerText = 'Overview of your played trivia games, accuracy, and streak records.';

      showCustomToast("Logged out to Guest Mode.");
      switchView('home-view');
    }

    /**
     * Records the result of a finished game (solo or multiplayer) into
     * the local `userStats` object and refreshes the dashboard. Accuracy
     * is a true running mean across every game played (each game counts
     * equally), using the standard
     * "new average = old average + (new value - old average) / n" formula.
     */
    function recordGameResult(quizTitle, finalScore, accuracyPct) {
      userStats.gamesPlayed += 1;
      userStats.totalPoints += finalScore;
      if (currentStreak > userStats.bestStreak) userStats.bestStreak = currentStreak;
      userStats.accuracy = Math.round(
        userStats.accuracy + (accuracyPct - userStats.accuracy) / userStats.gamesPlayed
      );

      userStats.history.unshift({
        title: quizTitle,
        role: currentUser ? currentUser.role : 'Guest',
        score: `${finalScore} pts`,
        accuracy: `${accuracyPct}%`,
        date: 'Just Now' // no real timestamp is stored, just a fixed label
      });

      updateDashboardStats();
    }

    /** Re-renders the 4 stat boxes and the history table on the dashboard from `userStats`. */
    function updateDashboardStats() {
      document.getElementById('dash-stat-games').innerText = userStats.gamesPlayed;
      document.getElementById('dash-stat-acc').innerText = `${userStats.accuracy}%`;
      document.getElementById('dash-stat-streak').innerText = `🔥 ${userStats.bestStreak}`;
      document.getElementById('dash-stat-points').innerText = userStats.totalPoints.toLocaleString();

      const tbody = document.getElementById('dash-history-rows');
      if (userStats.history.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No game history recorded yet. Play a solo or live game!</td></tr>`;
      } else {
        tbody.innerHTML = userStats.history.map(h => `
          <tr>
            <td><strong>${h.title}</strong></td>
            <td><span class="badge" style="font-size:0.65rem;">${h.role.toUpperCase()}</span></td>
            <td>${h.score}</td>
            <td style="color:var(--accent-green); font-weight:700;">${h.accuracy}</td>
            <td style="color:var(--text-muted);">${h.date}</td>
          </tr>
        `).join('');
      }
    }

    /**
     * Reads every .builder-question-card currently in the quiz-builder
     * modal, converts each one into the {type, question, "possible
     * responses", "correct answers"} shape the backend expects, and
     * POSTs the whole array via apiPostQuiz().
     */
    async function handleSaveBuilderQuiz() {
      const title = document.getElementById('builder-quiz-title').value || "New Custom Quiz";
      const cards = document.querySelectorAll('.builder-question-card');
      const quizPayload = [];

      cards.forEach((card, index) => {
        const qId = card.id.replace('builder-q-', '');
        const qText = card.querySelector('input[type="text"]').value; // the question's own text input (first text input in the card)
        const typeSelect = document.getElementById(`q-type-select-${qId}`).value;
        
        let typeStr = "short answer";
        let answers = [];
        let choices = [];

        if (typeSelect === 'short') {
          typeStr = "short answer";
          const ansVal = card.querySelector('.dynamic-answer-container input').value;
          answers = ansVal.split(',').map(s => s.trim());
        } else if (typeSelect === 'mc') {
          typeStr = "multiple choice";
          card.querySelectorAll('.choice-row').forEach(row => {
            const txt = row.querySelector('input[type="text"]').value;
            choices.push(txt);
            if (row.querySelector('input[type="radio"]').checked) answers.push(txt);
          });
        } else if (typeSelect === 'ms') {
          typeStr = "multiple select";
          card.querySelectorAll('.choice-row').forEach(row => {
            const txt = row.querySelector('input[type="text"]').value;
            choices.push(txt);
            if (row.querySelector('input[type="checkbox"]').checked) answers.push(txt);
          });
        } else if (typeSelect === 'tf') {
          typeStr = "multiple choice";
          choices = ["True", "False"];
          const isTrue = card.querySelectorAll('input[type="radio"]')[0].checked;
          answers.push(isTrue ? "True" : "False");
        }

        quizPayload.push({
          type: typeStr,
          question: qText,
          "possible responses": choices,
          "correct answers": answers
        });
      });

      // `title` isn't included in quizPayload - the backend's trivia JSON
      // spec has no title field (see trivia-manager.py), so there's
      // nowhere to put it server-side. It's kept locally instead, below.
      const backendIdx = await apiPostQuiz(quizPayload);
      if (backendIdx !== null) {
        // Remembers which backend trivia_set_idx this title maps to, so
        // "Host" for this quiz can open a real /api/rooms lobby against it.
        quizBackendIndex[title] = parseInt(backendIdx, 10);
      }
      closeModal('add-quiz-modal');
    }

    /**
     * Opens the full-page quiz detail view for the given quiz title,
     * looking it up in the local `quizDatabase`. All three home page
     * cards now have matching entries, but this still guards against
     * any future card being added without matching quiz data - in that
     * case it silently does nothing rather than crashing on `undefined`.
     */
    function openFullQuizPage(title) {
      const quiz = quizDatabase[title];
      if (!quiz) {
        showCustomToast(`No question data found for "${title}" yet.`); // FIXED: surface this instead of failing silently
        return;
      }

      document.getElementById('fullpage-quiz-title').innerText = title;
      document.getElementById('fullpage-quiz-tag').innerText = quiz.tag;
      document.getElementById('fullpage-question-count').innerText = quiz.questions.length;

      document.getElementById('fullpage-solo-btn').onclick = () => startSoloPlay(title);
      document.getElementById('fullpage-host-btn').onclick = () => openHostSetup(title);

      renderFullpageQuestions(quiz.questions);
      switchView('quiz-detail-view');
    }

    /** Builds the question cards on the quiz detail page, including the
     * (initially hidden) answer key section toggled by toggleFullpageAnswerKeys(). */
    function renderFullpageQuestions(questions) {
      const container = document.getElementById('fullpage-questions-container');
      container.innerHTML = '';

      questions.forEach((q, i) => {
        const card = document.createElement('div');
        card.className = 'fullpage-question-card';

        let choicesHTML = '';
        if (q.choices && q.choices.length > 0) {
          choicesHTML = `<div style="margin-top:0.75rem;">` + 
            q.choices.map(c => `<div class="fullpage-choice-item">⚪ ${c}</div>`).join('') + 
            `</div>`;
        }

        card.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:0.8rem; font-weight:700; color:var(--text-muted);">QUESTION ${i + 1}</span>
            <span class="badge">${q.type}</span>
          </div>
          <h4 style="margin: 0.5rem 0 0.25rem 0; font-size:1.05rem;">${q.q}</h4>
          ${choicesHTML}
          <div class="fullpage-answer-box" style="margin-top:0.75rem; font-size:0.85rem; color:var(--accent-green); display: ${showFullpageAnswers ? 'block' : 'none'};">
            ✓ Correct Answer Key: <strong>${q.answers.join(', ')}</strong>
          </div>
        `;
        container.appendChild(card);
      });
    }

    /** Flips the global answer-key visibility flag and shows/hides every answer box already on screen. */
    function toggleFullpageAnswerKeys() {
      showFullpageAnswers = !showFullpageAnswers;
      document.querySelectorAll('.fullpage-answer-box').forEach(el => {
        el.style.display = showFullpageAnswers ? 'block' : 'none';
      });
    }

    let questionCounter = 0; // ever-increasing id used to give each builder card a unique DOM id
    /**
     * Adds a new blank question card to the quiz builder modal, defaulting
     * to "Short Answer" type, and immediately calls updateAnswerFields()
     * so the answer inputs match that default type.
     */
    function addQuestionToBuilder() {
      questionCounter++;
      const container = document.getElementById('builder-questions-list');
      const card = document.createElement('div');
      card.className = 'builder-question-card';
      card.id = `builder-q-${questionCounter}`;

      card.innerHTML = `
        <button class="builder-remove-btn" onclick="document.getElementById('builder-q-${questionCounter}').remove()">✕ Remove</button>
        <div class="form-group">
          <label>Question ${questionCounter} Text</label>
          <input type="text" placeholder="Enter question..." required>
        </div>
        <div class="form-group">
          <label>Question Type</label>
          <select id="q-type-select-${questionCounter}" onchange="updateAnswerFields(${questionCounter})">
            <option value="short">Short Answer (Open-Ended)</option>
            <option value="mc">Multiple Choice (Single Select)</option>
            <option value="ms">Multiple Select (Checkboxes)</option>
            <option value="tf">True / False</option>
          </select>
        </div>
        <div id="dynamic-answer-box-${questionCounter}" class="dynamic-answer-container"></div>
      `;
      container.appendChild(card);
      updateAnswerFields(questionCounter);
    }

    /**
     * Re-renders the answer-input section of a builder question card to
     * match the currently selected question type. Called on initial add
     * and whenever the type <select> changes. Switching types replaces the
     * inner HTML entirely, so any answers already typed in for the
     * previous type are lost.
     */
    function updateAnswerFields(qId) {
      const type = document.getElementById(`q-type-select-${qId}`).value;
      const box = document.getElementById(`dynamic-answer-box-${qId}`);

      if (type === 'short') {
        box.innerHTML = `<label>Accepted Short Answer(s)</label><input type="text" placeholder="e.g. Port 80, 80">`;
      } else if (type === 'mc') {
        box.innerHTML = `
          <label>Options (Select correct radio)</label>
          <div class="choice-row"><input type="radio" name="mc-ans-${qId}" checked> <input type="text" value="TCP"></div>
          <div class="choice-row"><input type="radio" name="mc-ans-${qId}"> <input type="text" value="UDP"></div>
        `;
      } else if (type === 'ms') {
        box.innerHTML = `
          <label>Options (Check correct ones)</label>
          <div class="choice-row"><input type="checkbox" checked> <input type="text" value="HTTP"></div>
          <div class="choice-row"><input type="checkbox" checked> <input type="text" value="DNS"></div>
        `;
      } else if (type === 'tf') {
        box.innerHTML = `
          <label>Correct State</label>
          <div style="display:flex; gap:1rem;"><label><input type="radio" name="tf-ans-${qId}" checked> True</label><label><input type="radio" name="tf-ans-${qId}"> False</label></div>
        `;
      }
    }

    /** Updates the active avatar (both in state and in the Join Room preview UI). */
    function setAvatar(icon, label) {
      activeAvatar = { icon, name: label };
      document.getElementById('selected-avatar-icon').innerText = icon;
      document.getElementById('selected-avatar-label').innerText = label;
    }

    /**
     * Handles the "Enter Lobby" form submit on the Join Room page. Joins
     * via POST /api/rooms/join with a `room_code` field, and requires a
     * logged-in session (@require_login) - joining as a true anonymous
     * guest will get a 401 here. A successful join returns the full room
     * view (see lobby.public_room_view), which the backend also uses to
     * set session['idx_of_trivia_set']/['question_idx'], so GET /api/trivia
     * immediately serves the right quiz. Falls back to a local-only PIN
     * check (against `activeRoomPin`) only when the backend is completely
     * unreachable.
     */
    async function handleJoinGame(event) {
      event.preventDefault();
      const name = document.getElementById('name').value || 'Student';
      const enteredCode = document.getElementById('room').value.trim();

      try {
        const res = await fetch('/api/rooms/join', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ room_code: enteredCode })
        });

        if (res.ok) {
          const room = await res.json();
          activeRoomCode = room.room_code;
          isRoomHost = false;
          joinedRoomPacingMode = room.pacing_mode || 'self';
        } else if (res.status === 401) {
          showCustomToast("⚠️ You need to be logged in to join a room - please log in or sign up first.");
          return;
        } else {
          showCustomToast("⚠️ Invalid Room PIN on server!");
          return;
        }
      } catch(e) {
        // Backend unreachable - fall back to the purely local demo PIN.
        if (enteredCode !== activeRoomPin) {
          showCustomToast("⚠️ Invalid Room PIN!");
          return;
        }
        activeRoomCode = null;
        isRoomHost = false;
        joinedRoomPacingMode = 'self';
      }

      document.getElementById('player-avatar-display').innerText = activeAvatar.icon;
      document.getElementById('player-name-display').innerText = name;
      currentScore = 0; currentStreak = 0; currentQuestionIndex = 0;
      mpCorrectAnswers = 0; mpTotalAttempted = 0; // reset so this game's accuracy is tracked from scratch
      startHeartbeat(); // begin PING-ing every 5s per protocol_spec.json while actively playing
      await loadMultiplayerQuestion();
      showCustomToast(`Successfully Joined Lobby #${enteredCode}!`);
      switchView('gameplay-view');
    }

    /**
     * Loads the current multiplayer question from the live backend
     * (apiFetchTriviaQuestion), falling back to `quizDatabase[activeQuizTitle]`
     * only when the backend can't be reached at all, so a "World History
     * Essentials" or "Web Security & Cryptography" session still shows
     * the right questions when fully offline.
     * When a real API question is returned, the code reads `apiQ.question`
     * for the display text, while the local fallback objects use the key
     * `q.q` instead - each path reads the field name that matches its own
     * data source. In a host-paced room, this also starts
     * startStudentQuestionPolling() so the player picks up whatever
     * question the host dispatches next, without advancing on their own.
     */
    async function loadMultiplayerQuestion() {
      const apiQ = await apiFetchTriviaQuestion();
      if (apiQ && apiQ.serverSignaledDone) {
        // Reached the backend, but the session has run past the last
        // question in the trivia set - the quiz is genuinely finished.
        const accuracyPct = mpTotalAttempted > 0 ? Math.round((mpCorrectAnswers / mpTotalAttempted) * 100) : 100;
        showCustomToast(`Quiz Completed! Final Score: ${currentScore}`);
        recordGameResult(activeQuizTitle, currentScore, accuracyPct);
        stopHeartbeat();
        stopStudentQuestionPolling();
        switchView('dashboard-view');
        return;
      }
      if (apiQ) {
        localCurrentQuestion = apiQ;
        lastSeenQuestionText = apiQ.question;
        document.getElementById('current-question-text').innerText = apiQ.question;
        document.getElementById('ans').value = '';
        // Unlike the fallback branch below, this branch doesn't update
        // #question-progress-badge ("Question X of Y"), since the API
        // response doesn't carry a total question count.
        if (joinedRoomPacingMode === 'host') {
          startStudentQuestionPolling();
        }
      } else {
        const sampleQuestions = quizDatabase[activeQuizTitle].questions;
        if (currentQuestionIndex < sampleQuestions.length) {
          localCurrentQuestion = sampleQuestions[currentQuestionIndex];
          document.getElementById('question-progress-badge').innerText = `Question ${currentQuestionIndex + 1} of ${sampleQuestions.length}`;
          document.getElementById('current-question-text').innerText = sampleQuestions[currentQuestionIndex].q;
          document.getElementById('ans').value = '';
        } else {
          // Accuracy is computed from actual correct/attempted counts
          // (mpCorrectAnswers / mpTotalAttempted), and the quiz is
          // recorded under activeQuizTitle.
          const accuracyPct = mpTotalAttempted > 0 ? Math.round((mpCorrectAnswers / mpTotalAttempted) * 100) : 100;
          showCustomToast(`Quiz Completed! Final Score: ${currentScore}`);
          recordGameResult(activeQuizTitle, currentScore, accuracyPct);
          stopHeartbeat(); // no need to keep pinging once the game is over
          switchView('dashboard-view');
        }
      }
    }

    /**
     * Polls GET /api/trivia every 2 seconds for a player in a host-paced
     * room, and refreshes the displayed question whenever the text
     * changes - this is how a student picks up whatever the host just
     * dispatched via "Next Question", since players in host-paced rooms
     * never advance their own question index (see handleAnswerSubmit()
     * and next_question()'s 403 in server.py).
     */
    function startStudentQuestionPolling() {
      stopStudentQuestionPolling();
      studentQuestionPollInterval = setInterval(pollForHostAdvance, 2000);
    }

    function stopStudentQuestionPolling() {
      clearInterval(studentQuestionPollInterval);
      studentQuestionPollInterval = null;
    }

    async function pollForHostAdvance() {
      const apiQ = await apiFetchTriviaQuestion();
      if (!apiQ) return; // backend unreachable this tick - try again next poll
      if (apiQ.serverSignaledDone) {
        const accuracyPct = mpTotalAttempted > 0 ? Math.round((mpCorrectAnswers / mpTotalAttempted) * 100) : 100;
        showCustomToast(`Quiz Completed! Final Score: ${currentScore}`);
        recordGameResult(activeQuizTitle, currentScore, accuracyPct);
        stopHeartbeat();
        stopStudentQuestionPolling();
        switchView('dashboard-view');
        return;
      }
      if (apiQ.question !== lastSeenQuestionText) {
        localCurrentQuestion = apiQ;
        lastSeenQuestionText = apiQ.question;
        document.getElementById('current-question-text').innerText = apiQ.question;
        document.getElementById('ans').value = '';
        showCustomToast('➔ The host moved everyone to the next question.');
      }
    }

    /**
     * Handles submitting an answer during a multiplayer game.
     * Tries the server-side verify endpoint first (apiVerifyAnswer - see
     * the note there about the GET-with-body backend limitation), then
     * falls back to local grading via checkAnswerAgainstQuestion(), which
     * requires an exact set match for "Multiple Select" questions. In a
     * host-paced room, the player does not advance to the next question
     * themselves after answering - server.py's next_question() rejects
     * that with a 403, so instead the poll loop started in
     * loadMultiplayerQuestion() picks up whatever the host dispatches.
     */
    async function handleAnswerSubmit(event) {
      event.preventDefault();
      const userAnsRaw = document.getElementById('ans').value;
      const questionForGrading = localCurrentQuestion
        ? { type: localCurrentQuestion.type, answers: localCurrentQuestion.answers || localCurrentQuestion['correct answers'] || [] }
        : { type: '', answers: [] };
      const { isCorrect: localIsCorrect, answerArray } = checkAnswerAgainstQuestion(questionForGrading, userAnsRaw);

      let isCorrect = await apiVerifyAnswer(answerArray);
      if (isCorrect === null) {
        isCorrect = localIsCorrect; // backend call didn't succeed - trust local grading
      }

      mpTotalAttempted++; // tracked so end-of-game accuracy reflects real performance
      if (isCorrect) {
        mpCorrectAnswers++;
        currentScore += 1000; currentStreak += 1;
        showCustomToast("✓ Correct! +1,000 points awarded.");
      } else {
        currentStreak = 0;
        showCustomToast(`✕ Incorrect (0 Points)`);
      }

      document.getElementById('player-score').innerText = currentScore;
      document.getElementById('player-streak').innerText = `🔥 ${currentStreak}x`;

      if (joinedRoomPacingMode === 'host') {
        document.getElementById('ans').value = '';
        showCustomToast('Waiting for the host to advance to the next question...');
      } else {
        await apiNextQuestion();
        currentQuestionIndex++;
        setTimeout(loadMultiplayerQuestion, 1200);
      }
    }

    /* ---------- Solo Practice Arcade ---------- */

    /**
     * Starts a solo practice run for the given quiz title. Looks up the
     * quiz by `quizTitle` and stores it in `activeQuizTitle` so the rest
     * of the solo flow (handleSoloAnswerSubmit, recordGameResult) stays
     * in sync. If a quiz title has no local data yet, falls back to
     * Networking Protocols and lets the user know via toast.
     */
    function startSoloPlay(quizTitle) {
      const quiz = quizDatabase[quizTitle];
      if (!quiz) {
        showCustomToast(`No question data found for "${quizTitle}" yet - starting Networking Protocols instead.`);
      }
      activeQuizTitle = quiz ? quizTitle : 'Networking Protocols';
      const sampleQuestions = quizDatabase[activeQuizTitle].questions;

      currentQuestionIndex = 0; currentScore = 0; currentStreak = 0;
      soloCorrectAnswers = 0; soloTotalAttempted = 0;

      document.getElementById('solo-progress-badge').innerText = `Q 1 / ${sampleQuestions.length}`;
      document.getElementById('solo-question-text').innerText = sampleQuestions[0].q;
      document.getElementById('solo-ans').value = '';
      document.getElementById('solo-score-val').innerText = '0 PTS';
      document.getElementById('solo-accuracy-val').innerText = '100%';
      document.getElementById('solo-feedback-banner').style.display = 'none';

      showCustomToast(`Solo Practice Started: ${activeQuizTitle}`);
      switchView('solo-gameplay-view');
    }

    /**
     * Grades a solo-mode answer entirely client-side (no backend call at
     * all here - solo mode is meant to work fully offline), updates
     * score/streak/accuracy, shows a feedback banner, then after 1.6s
     * either advances to the next question or finishes the run and
     * records it via recordGameResult(). Reads from
     * quizDatabase[activeQuizTitle] (set by startSoloPlay), and uses
     * checkAnswerAgainstQuestion() so "Multiple Select" questions require
     * an exact set match (matching trivia-manager.py's grading rule).
     */
    function handleSoloAnswerSubmit(event) {
      event.preventDefault();
      const sampleQuestions = quizDatabase[activeQuizTitle].questions;
      const userAnsRaw = document.getElementById('solo-ans').value;
      const currentQ = sampleQuestions[currentQuestionIndex];
      const feedbackBanner = document.getElementById('solo-feedback-banner');

      const { isCorrect } = checkAnswerAgainstQuestion(currentQ, userAnsRaw);
      soloTotalAttempted++;

      if (isCorrect) {
        soloCorrectAnswers++; currentStreak += 1;
        currentScore += 1000;
        feedbackBanner.className = 'answer-feedback-banner feedback-correct';
        feedbackBanner.innerText = `✓ CORRECT ANSWER! +1,000 PTS`;
      } else {
        currentStreak = 0;
        feedbackBanner.className = 'answer-feedback-banner feedback-incorrect';
        // Shows every accepted answer now (joined), not just answers[0],
        // since Multiple Select questions need every item to be visible.
        feedbackBanner.innerText = `✕ INCORRECT. Correct answer was: "${currentQ.answers.join(', ')}"`;
      }

      const accuracyPct = Math.round((soloCorrectAnswers / soloTotalAttempted) * 100);

      feedbackBanner.style.display = 'block';
      document.getElementById('solo-score-val').innerText = `${currentScore} PTS`;
      document.getElementById('solo-accuracy-val').innerText = `${accuracyPct}%`;

      currentQuestionIndex++;
      setTimeout(() => {
        feedbackBanner.style.display = 'none';
        if (currentQuestionIndex < sampleQuestions.length) {
          document.getElementById('solo-progress-badge').innerText = `Q ${currentQuestionIndex + 1} / ${sampleQuestions.length}`;
          document.getElementById('solo-question-text').innerText = sampleQuestions[currentQuestionIndex].q;
          document.getElementById('solo-ans').value = '';
        } else {
          showCustomToast(`Solo Practice Finished! Accuracy: ${accuracyPct}% | Score: ${currentScore}`);
          // Records under the quiz that was actually played (activeQuizTitle).
          recordGameResult(activeQuizTitle, currentScore, accuracyPct);
          switchView('dashboard-view');
        }
      }, 1600);
    }

    /* ---------- Host Setup & Live Session ---------- */

    /**
     * Opens the Host Setup page pre-filled with the chosen quiz title,
     * defaulting to self-paced mode. Records the choice in
     * `activeQuizTitle` (falling back to Networking Protocols if there's
     * no local data for this quiz yet) so the live session uses the right
     * question set.
     */
    function openHostSetup(quizTitle) {
      const quiz = quizDatabase[quizTitle];
      if (!quiz) {
        showCustomToast(`No question data found for "${quizTitle}" yet - hosting Networking Protocols instead.`);
      }
      activeQuizTitle = quiz ? quizTitle : 'Networking Protocols';
      document.getElementById('host-quiz-title').value = activeQuizTitle;
      selectPacingMode('self');
      switchView('host-setup-view');
    }

    /** Toggles which pacing mode card looks "selected" and shows/hides the host-paced-only settings block. */
    function selectPacingMode(mode) {
      selectedPacing = mode;
      const selfCard = document.getElementById('mode-card-self');
      const hostCard = document.getElementById('mode-card-host');
      const hostSettingsGroup = document.getElementById('host-paced-settings-group');

      if (mode === 'self') {
        selfCard.classList.add('selected');
        hostCard.classList.remove('selected');
        hostSettingsGroup.style.display = 'none';
      } else {
        hostCard.classList.add('selected');
        selfCard.classList.remove('selected');
        hostSettingsGroup.style.display = 'block';
      }
    }

    /** Shows/hides the timer-duration dropdown depending on whether the countdown timer is enabled. */
    function toggleTimerDurationDropdown() {
      const isTimerEnabled = document.getElementById('host-enable-timer-select').value === 'yes';
      document.getElementById('timer-duration-wrapper').style.display = isTimerEnabled ? 'block' : 'none';
    }

    /**
     * Keeps #host-current-q-label showing "Current Question: X of Y",
     * using hostQuestionIndex and the active quiz's question count. This
     * is local-only bookkeeping, not driven by the backend's own question
     * sync.
     */
    function updateHostCurrentQuestionLabel() {
      const total = quizDatabase[activeQuizTitle].questions.length;
      const label = document.getElementById('host-current-q-label');
      if (hostQuestionIndex >= total) {
        label.innerText = `Current Question: Finished (${total} of ${total})`;
      } else {
        label.innerText = `Current Question: ${hostQuestionIndex + 1} of ${total}`;
      }
    }

    /**
     * Creates a live room via POST /api/rooms (server (1).py's real lobby
     * API). UPDATED from the old version, which generated its own PIN
     * client-side and posted to the now-removed /api/room/create:
     *   - the PIN ("room_code") is now generated SERVER-SIDE and comes
     *     back in the response - we display whatever the server gives us.
     *   - requires a Teacher-role session (@require_role("teacher")); on
     *     403/401 we now tell the user clearly instead of silently
     *     pretending it worked.
     *   - idx_of_trivia_set must be a REAL backend trivia set index. We
     *     look it up from quizBackendIndex[activeQuizTitle] (filled in by
     *     handleSaveBuilderQuiz() after a successful save) - if this quiz
     *     was never uploaded to the server this run, the server will
     *     reply 404 "trivia set not found", which we also surface clearly.
     * Falls back to a fully local/offline demo room only when the network
     * call itself fails (e.g. no backend running at all).
     */
    async function launchHostLobby(event) {
      event.preventDefault();

      const hostPacedControls = document.getElementById('host-paced-control-container');
      const studentPacedBanner = document.getElementById('student-paced-status-container');
      const modeBadge = document.getElementById('host-mode-badge');
      const timerDisplay = document.getElementById('host-timer-display');
      const startBtn = document.getElementById('host-start-session-btn');

      const idxOfTriviaSet = quizBackendIndex[activeQuizTitle];
      let joinedLive = false;
      const liveStatusEl = document.getElementById('host-pin-live-status');

      if (idxOfTriviaSet !== undefined) {
        try {
          const res = await fetch('/api/rooms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ idx_of_trivia_set: idxOfTriviaSet, pacing_mode: selectedPacing })
          });
          if (res.ok) {
            const room = await res.json(); // 201 - {room_code, status:'waiting', players:[...], ...}
            activeRoomCode = room.room_code;
            activeRoomPin = room.room_code;
            isRoomHost = true;
            joinedLive = true;
            startBtn.style.display = 'inline-block';
          } else if (res.status === 401 || res.status === 403) {
            showCustomToast("⚠️ Hosting a live room requires a Teacher account - continuing in local-only demo mode.");
          } else if (res.status === 404) {
            showCustomToast(`⚠️ "${activeQuizTitle}" wasn't found on the server (trivia set #${idxOfTriviaSet}) - continuing in local-only demo mode.`);
          } else {
            showCustomToast("⚠️ Server rejected the room request - continuing in local-only demo mode.");
          }
        } catch(e) {
          console.log("Running room locally - backend unreachable");
        }
      } else {
        showCustomToast(`ℹ️ "${activeQuizTitle}" hasn't been saved to the server yet, so this will be a local-only demo room. Use "Build New Quiz" to save it first for a real live session.`);
      }

      if (!joinedLive) {
        // Local-only fallback: invent our own PIN just so the demo UI has
        // something to show, same as the app behaved before the real
        // lobby API existed.
        activeRoomPin = Math.floor(1000 + Math.random() * 9000).toString();
        activeRoomCode = null;
        isRoomHost = false;
        startBtn.style.display = 'none';
      }

      document.getElementById('host-pin-display').innerText = `#${activeRoomPin}`;
      if (joinedLive) {
        liveStatusEl.innerText = '🟢 Live - other devices can join with this PIN';
        liveStatusEl.style.color = 'var(--accent-neon, #22c55e)';
      } else {
        liveStatusEl.innerText = '⚠️ Local demo only - no one else can join this PIN';
        liveStatusEl.style.color = '#f59e0b';
      }
      liveStatusEl.style.display = 'block';

      clearInterval(hostTimerInterval);

      if (selectedPacing === 'self') {
        hostPacedControls.style.display = 'none';
        studentPacedBanner.style.display = 'block';
        modeBadge.innerText = 'SELF-PACED SESSION';
      } else {
        hostPacedControls.style.display = 'flex';
        studentPacedBanner.style.display = 'none';
        modeBadge.innerText = 'HOST-PACED SESSION';

        const enableTimer = document.getElementById('host-enable-timer-select').value === 'yes';
        if (enableTimer) {
          const duration = parseInt(document.getElementById('host-timer-duration').value);
          timerDisplay.style.display = 'flex';
          startHostTimer(duration);
        } else {
          timerDisplay.style.display = 'none';
        }

        hostQuestionIndex = 0; // reset progress counter for this new session
        updateHostCurrentQuestionLabel();
      }

      if (joinedLive) {
        startRoomStandingsPolling(); // keeps the standings table live
        startHeartbeat();
      }

      showCustomToast(`Host Session Created! Room PIN: #${activeRoomPin}`);
      switchView('host-scoreboard-view');
    }

    /**
     * Host-only action: flips the room from "waiting" to "active" via
     * POST /api/rooms/<code>/start. Only meaningful for a real
     * (non-local-fallback) room, since local rooms have no backend state.
     */
    async function handleStartRoom() {
      if (!activeRoomCode) {
        showCustomToast("This is a local-only demo room - nothing to start on the server.");
        return;
      }
      try {
        const res = await fetch(`/api/rooms/${activeRoomCode}/start`, { method: 'POST' });
        if (res.ok) {
          showCustomToast("▶️ Session started - players can now begin!");
        } else if (res.status === 403) {
          showCustomToast("⚠️ Only the host who created this room can start it.");
        } else {
          showCustomToast("⚠️ Couldn't start the session on the server.");
        }
      } catch(e) {
        showCustomToast("⚠️ Server unreachable - couldn't start the session.");
      }
    }

    /**
     * Ends the live session. For a real room this tells the backend the
     * host left (POST /api/rooms/leave), which - per leave_room() in
     * trivia-manager.py - marks the whole room "ended" since the host is
     * leaving. Always stops local polling/heartbeats and returns home
     * regardless of whether the backend call succeeds.
     */
    async function handleEndSession() {
      if (activeRoomCode) {
        try {
          await fetch('/api/rooms/leave', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_code: activeRoomCode })
          });
        } catch(e) {
          console.log("Couldn't reach server to close the room - ending locally anyway.");
        }
      }
      stopRoomStandingsPolling();
      stopHeartbeat();
      activeRoomCode = null;
      isRoomHost = false;
      switchView('home-view');
    }

    /**
     * Polls GET /api/rooms/<code> (roster) and
     * GET /api/rooms/<code>/connectivity (heartbeat-based online/offline
     * status, per player) together every 3 seconds while the host
     * scoreboard is open, and renders both into #host-standings-tbody.
     */
    function startRoomStandingsPolling() {
      stopRoomStandingsPolling();
      pollRoomStandings(); // fetch immediately, don't wait 3s for the first paint
      roomPollInterval = setInterval(pollRoomStandings, 3000);
    }

    function stopRoomStandingsPolling() {
      clearInterval(roomPollInterval);
      roomPollInterval = null;
    }

    async function pollRoomStandings() {
      if (!activeRoomCode) return;
      try {
        const [roomRes, connRes] = await Promise.all([
          fetch(`/api/rooms/${activeRoomCode}`),
          fetch(`/api/rooms/${activeRoomCode}/connectivity`)
        ]);
        if (!roomRes.ok) return;
        const room = await roomRes.json();
        const connectivity = connRes.ok ? await connRes.json() : { players: [] };
        const connectedByUuid = {};
        connectivity.players.forEach(p => { connectedByUuid[p.UUID] = p.connected; });
        renderRoomStandings(room, connectedByUuid);
      } catch(e) {
        // Silent - this just means the next poll will try again in 3s.
      }
    }

    function renderRoomStandings(room, connectedByUuid = {}) {
      const tbody = document.getElementById('host-standings-tbody');
      if (!room.players || room.players.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Waiting for players to join room...</td></tr>`;
        return;
      }
      tbody.innerHTML = room.players.map((p, i) => {
        const isConnected = connectedByUuid[p.UUID];
        const statusHTML = isConnected === undefined
          ? `<span style="color: var(--text-muted);">—</span>`
          : isConnected
            ? `<span style="color: var(--accent-green);">🟢 Online</span>`
            : `<span style="color: var(--accent-red);">🔴 Offline</span>`;
        return `
        <tr>
          <td>#${i + 1}</td>
          <td><strong>${p.username}</strong></td>
          <td><span class="badge" style="font-size:0.65rem;">${(p.role || 'student').toUpperCase()}</span></td>
          <td>${statusHTML}</td>
          <td style="color: var(--text-muted);">— (backend doesn't expose per-player score yet)</td>
        </tr>
      `;
      }).join('');
    }

    /* ---------- Heartbeat (protocol_spec.json HEARTBEAT / PING-PONG) ---------- */

    /** Sends one PING; best-effort, failures are silently ignored (heartbeats are non-critical). */
    async function sendHeartbeat() {
      try {
        await fetch('/api/heartbeat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: 'PING', timestamp: Math.floor(Date.now() / 1000) })
        });
      } catch(e) { /* offline - next tick will try again */ }
    }

    /** Starts a 5-second PING loop (matches reliability.py's HEARTBEAT_INTERVAL_SECONDS). */
    function startHeartbeat() {
      stopHeartbeat();
      sendHeartbeat();
      heartbeatInterval = setInterval(sendHeartbeat, 5000);
    }

    function stopHeartbeat() {
      clearInterval(heartbeatInterval);
      heartbeatInterval = null;
    }

    /** Runs a simple 1-second-tick countdown in the host's timer circle; clears/replaces any previous timer first. */
    function startHostTimer(durationSeconds) {
      clearInterval(hostTimerInterval);
      let timeLeft = durationSeconds;
      const display = document.getElementById('host-timer-display');
      display.innerText = timeLeft;

      hostTimerInterval = setInterval(() => {
        timeLeft--;
        display.innerText = timeLeft;
        if (timeLeft <= 0) {
          clearInterval(hostTimerInterval);
          showCustomToast("⏱️ Time expired for current question!");
        }
      }, 1000);
    }

    /**
     * Host-paced "Next Question" button handler: restarts the countdown
     * (if enabled) and calls POST /api/rooms/<code>/next, which advances
     * the room's shared question index server-side - every player's poll
     * loop (see startStudentQuestionPolling()) picks up the change within
     * a couple seconds. Only works for a real (non-local-fallback) room;
     * local demo rooms have no backend room state to advance.
     */
    async function dispatchNextHostQuestion() {
      const enableTimer = document.getElementById('host-enable-timer-select').value === 'yes';
      if (enableTimer) {
        const duration = parseInt(document.getElementById('host-timer-duration').value);
        startHostTimer(duration);
      }

      if (!activeRoomCode) {
        showCustomToast("This is a local-only demo room - there's no live room to dispatch to.");
        hostQuestionIndex++;
        updateHostCurrentQuestionLabel();
        return;
      }

      try {
        const res = await fetch(`/api/rooms/${activeRoomCode}/next`, { method: 'POST' });
        if (res.ok) {
          hostQuestionIndex++;
          updateHostCurrentQuestionLabel();
          showCustomToast("Dispatched next question to participants!");
        } else if (res.status === 403) {
          showCustomToast("⚠️ Only the host who created this room can advance it.");
        } else if (res.status === 409) {
          showCustomToast("⚠️ The room isn't active yet - press Start Session first.");
        } else {
          showCustomToast("⚠️ Couldn't advance the question on the server.");
        }
      } catch(e) {
        showCustomToast("⚠️ Server unreachable - couldn't dispatch the next question.");
      }
    }

    /**
     * Core "page navigation" function for this single-page app.
     * Hides every .view, shows only the one matching viewId, and updates
     * which nav button looks active by checking whose onclick attribute
     * string contains viewId (a simple but slightly fragile trick - it
     * works here because each nav button's onclick literally contains
     * the view id as a substring). Also stops the standings-polling loop
     * when leaving the host scoreboard, and stops the heartbeat loop when
     * leaving the multiplayer gameplay view, so switching pages mid-game
     * doesn't leave background fetch loops running.
     */
    function switchView(viewId) {
      if (viewId !== 'host-scoreboard-view') {
        clearInterval(hostTimerInterval); // stop the host countdown if we navigate away
        stopRoomStandingsPolling();
      }
      if (viewId !== 'gameplay-view') {
        stopHeartbeat();
        stopStudentQuestionPolling();
      }
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      const target = document.getElementById(viewId);
      if (target) target.classList.add('active');

      document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(viewId)) {
          btn.classList.add('active');
        }
      });
    }

    /** Flips the data-theme attribute on <html> between 'dark' and 'light', which the CSS variables react to. */
    function toggleTheme() {
      const html = document.documentElement;
      const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', newTheme);
      document.getElementById('theme-icon').innerText = newTheme === 'dark' ? '🌙' : '☀️';
      document.getElementById('theme-text').innerText = newTheme === 'dark' ? 'Dark' : 'Light';
    }

    /**
     * Reliability feature: RECONNECT (GET /api/reconnect). On page load,
     * silently asks the backend "was this session (identified by the
     * existing login cookie) in the middle of a multiplayer game?" - this
     * covers the case where a player's browser tab reloads or their Wi-Fi
     * drops and reconnects mid-quiz. Does nothing (no toast, no view
     * change) if the person isn't logged in (401) or has no saved
     * progress (404) - which is the normal case for most page loads.
     * Only resumes the room-based (multiplayer) case, since that's what
     * reliability.py's save_reconnect_state() tracks; solo practice has
     * no server-side progress to restore.
     */
    async function attemptReconnect() {
      try {
        const res = await fetch('/api/reconnect');
        if (!res.ok) return; // not logged in, or nothing to resume - normal case
        const state = await res.json();
        if (!state.room_code) return; // no room bound to this session

        activeRoomCode = state.room_code;
        currentQuestionIndex = state.question_idx || 0;
        isRoomHost = false;

        // The saved state doesn't include pacing_mode, so look it up from
        // the room itself to decide whether this player should poll for
        // host dispatches or advance on their own.
        try {
          const roomRes = await fetch(`/api/rooms/${activeRoomCode}`);
          if (roomRes.ok) {
            const room = await roomRes.json();
            joinedRoomPacingMode = room.pacing_mode || 'self';
          }
        } catch(e) { /* falls back to 'self' if this lookup fails */ }

        document.getElementById('player-avatar-display').innerText = activeAvatar.icon;
        document.getElementById('player-name-display').innerText = 'Reconnected Player';
        currentScore = 0; currentStreak = 0;
        mpCorrectAnswers = 0; mpTotalAttempted = 0;
        startHeartbeat();
        await loadMultiplayerQuestion();
        showCustomToast('🔄 Reconnected - resuming your previous session.');
        switchView('gameplay-view');
      } catch(e) {
        // Backend unreachable - nothing to reconnect to right now.
      }
    }

    // On page load, add one blank question card to the quiz builder so
    // the modal never opens completely empty, and check whether this
    // session has a dropped multiplayer game to resume.
    document.addEventListener('DOMContentLoaded', () => {
      addQuestionToBuilder();
      attemptReconnect();
    });
