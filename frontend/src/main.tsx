import ReactDOM from "react-dom/client";
import App from "./App";
import { AuthGate } from "./components/AuthGate";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <AuthGate>
    {(user, signOut, updateUser) => (
      <App
        currentUser={user}
        onLogout={signOut}
        onUserChanged={updateUser}
      />
    )}
  </AuthGate>
);
