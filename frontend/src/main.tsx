import ReactDOM from "react-dom/client";
import App from "./App";
import { AuthGate } from "./components/AuthGate";
import { ThemeProvider, applyTheme, readTheme } from "./theme";
import "./theme.css";

applyTheme(readTheme());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <AuthGate>
      {(user, signOut, updateUser) => (
        <App
          currentUser={user}
          onLogout={signOut}
          onUserChanged={updateUser}
        />
      )}
    </AuthGate>
  </ThemeProvider>
);
