package dev.nexus.smoke;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private int taps = 0;

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(24), dp(24), dp(24), dp(24));
        root.setBackgroundColor(Color.rgb(15, 18, 24));

        TextView title = new TextView(this);
        title.setText("Built entirely on this phone");
        title.setTextColor(Color.rgb(225, 231, 239));
        title.setTextSize(24);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        final TextView status = new TextView(this);
        status.setText("Termux → javac → D8 → AAPT → signed APK");
        status.setTextColor(Color.rgb(148, 163, 184));
        status.setTextSize(15);
        status.setGravity(Gravity.CENTER);
        status.setPadding(0, dp(16), 0, dp(24));
        root.addView(status);

        Button button = new Button(this);
        button.setText("Test the app");
        button.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                taps += 1;
                status.setText("It works — tap " + taps);
            }
        });
        root.addView(button);

        setContentView(root);
    }
}
