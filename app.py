from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "change_this_to_a_random_secret_key"

# -------------------------
# Grade / SGPA logic
# -------------------------
def calculate_sgpa(marks):
    if not marks:
        return 0
    return round(sum(marks) / len(marks) / 10, 2)

def assign_grade(sgpa):
    if sgpa >= 9:
        return "O"
    elif sgpa >= 8:
        return "A+"
    elif sgpa >= 7:
        return "A"
    elif sgpa >= 6:
        return "B"
    elif sgpa >= 5:
        return "C"
    else:
        return "F"

def give_suggestions(sgpa):
    if sgpa >= 9:
        return "Excellent! Keep it up!"
    elif sgpa >= 8:
        return "Good! You can improve further to reach 9+."
    elif sgpa >= 7:
        return "Nice! Try to focus a bit more on weak areas."
    elif sgpa >= 6:
        return "Average performance. Work harder to improve."
    else:
        return "Need serious improvement. Focus on your studies."

# -------------------------
# CSV parsing -> students
# -------------------------
def parse_df_to_students(df):
    students = {}
    subjects = []
    for col in df.columns:
        if col.endswith("_marks"):
            subjects.append(col.replace("_marks", ""))
    subjects = sorted(list(set(subjects)))

    if df.shape[0] == 0:
        return {}, subjects

    name_col = df.columns[0]

    for _, row in df.iterrows():
        name = str(row[name_col]) if not pd.isna(row[name_col]) else "Unknown"
        marks = []
        display_marks = []
        absents = 0
        attendance = {}
        for sub in subjects:
            mark_col = f"{sub}_marks"
            att_col = f"{sub}_attendance"
            val = row.get(mark_col, "")
            if pd.isna(val) or str(val).strip() == "":
                marks.append(0)
                display_marks.append("Absent")
                absents += 1
            else:
                try:
                    m = float(val)
                except:
                    m = 0.0
                marks.append(m)
                display_marks.append(m)
            att_val = row.get(att_col, 0)
            try:
                attendance[sub] = float(att_val)
            except:
                attendance[sub] = 0.0

        sgpa = calculate_sgpa(marks)
        grade = assign_grade(sgpa)
        suggestion = give_suggestions(sgpa)
        low_attendance = [sub for sub, att in attendance.items() if att < 75]
        if low_attendance:
            suggestion += f" | ⚠ Improve attendance in: {', '.join(low_attendance)}."
        total = sum(marks)

        students[name] = {
            "marks": display_marks,
            "total": total,
            "sgpa": sgpa,
            "grade": grade,
            "absents": absents,
            "attendance": attendance,
            "suggestion": suggestion
        }

    return students, subjects

# -------------------------
# Build Plotly figures (return Python dicts)
# -------------------------
def build_figures(students, subjects):
    names = list(students.keys())
    if not names:
        # return empty simple figures
        empty = {"data": [], "layout": {}}
        return {"sgpa": empty, "grade": empty, "att_vs_sgpa": empty, "heatmap": empty, "stacked": empty, "per_student_att": []}

    sgpas = [students[n]["sgpa"] for n in names]

    # SGPA bar
    fig_sgpa = go.Figure([go.Bar(x=names, y=sgpas)])
    fig_sgpa.update_layout(title="SGPA Comparison", yaxis=dict(range=[0,10]))

    # Grade distribution pie
    grades = [students[n]["grade"] for n in names]
    grade_counts = pd.Series(grades).value_counts()
    fig_grade = go.Figure(data=[go.Pie(labels=grade_counts.index.tolist(),
                                       values=grade_counts.values,
                                       hole=0.2)])
    fig_grade.update_layout(title="Grade Distribution")

    # Attendance vs SGPA scatter
    avg_att = []
    for n in names:
        att_vals = list(students[n]["attendance"].values())
        avg = (sum(att_vals) / len(att_vals)) if att_vals else 0
        avg_att.append(avg)
    fig_att_sgpa = go.Figure()
    fig_att_sgpa.add_trace(go.Scatter(x=avg_att, y=sgpas, mode="markers+text", text=names, textposition="top center"))
    fig_att_sgpa.update_layout(title="Average Attendance vs SGPA", xaxis_title="Avg Attendance (%)", yaxis_title="SGPA")

    # Heatmap: subjects x students
    heat_z = []
    for sub in subjects:
        row = []
        for n in names:
            val = students[n]["marks"][subjects.index(sub)]
            row.append(val if isinstance(val, (int, float)) else 0)
        heat_z.append(row)
    fig_heat = go.Figure(data=go.Heatmap(z=heat_z, x=names, y=subjects, colorscale="YlGnBu", hoverongaps=False))
    fig_heat.update_layout(title="Subject-wise Marks Heatmap (Subjects as rows)")

    # Stacked marks per subject
    stacks = []
    for sub in subjects:
        stacks.append([students[n]["marks"][subjects.index(sub)] if isinstance(students[n]["marks"][subjects.index(sub)], (int, float)) else 0 for n in names])
    fig_stack = go.Figure()
    for i, sub in enumerate(subjects):
        fig_stack.add_trace(go.Bar(x=names, y=stacks[i], name=sub))
    fig_stack.update_layout(barmode='stack', title="Subject-wise Marks (Stacked)")

    # Per-student attendance figures (as dicts)
    per_student_att = []
    for n in names:
        att_vals = [students[n]["attendance"].get(sub, 0) for sub in subjects]
        fig = go.Figure([go.Bar(x=subjects, y=att_vals)])
        fig.update_layout(title=f"{n} - Attendance by Subject", yaxis=dict(range=[0,100]))
        per_student_att.append((n, fig.to_dict()))

    figs = {
        "sgpa": fig_sgpa.to_dict(),
        "grade": fig_grade.to_dict(),
        "att_vs_sgpa": fig_att_sgpa.to_dict(),
        "heatmap": fig_heat.to_dict(),
        "stacked": fig_stack.to_dict(),
        "per_student_att": per_student_att
    }
    return figs

# -------------------------
# Routes
# -------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file:
            flash("Please upload a CSV file.", "danger")
            return redirect(url_for("index"))
        try:
            df = pd.read_csv(file)
        except Exception as e:
            flash(f"Could not read CSV: {e}", "danger")
            return redirect(url_for("index"))

        students, subjects = parse_df_to_students(df)
        if not students:
            flash("No student rows found in the CSV.", "warning")
            return redirect(url_for("index"))

        figs = build_figures(students, subjects)

        # compute class summary
        sgpas = [info["sgpa"] for info in students.values()]
        class_summary = {
            "avg_sgpa": round(np.mean(sgpas), 2) if sgpas else 0,
            "max_sgpa": round(np.max(sgpas), 2) if sgpas else 0,
            "min_sgpa": round(np.min(sgpas), 2) if sgpas else 0
        }

        return render_template("index.html",
                               students=students,
                               subjects=subjects,
                               figs=figs,
                               class_summary=class_summary)
    return render_template("index.html", students=None)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
